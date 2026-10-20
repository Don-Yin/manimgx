//! The stage: the GPU's player for Python (`python`), with a thread of its own. Python's calls —
//! uploads, evictions, its video's frames — are queued as it makes them and carried out on the
//! stage's thread in the order they were made, as the player (`render`) and its video (`export`)
//! would carry them out on Python's thread; so a scene does not wait for the GPU or the encoder.
//! What Python waits for — pixels, its video's end — it carries out itself, on its own thread,
//! once every call made before is carried out (`now`): nothing crosses threads to answer it. What
//! is queued and not yet carried out is bounded (`QUEUED` bytes): past it, Python waits for room.
//!
//! Something going wrong on the stage's thread — the GPU, the encoder, an upload the player
//! refuses — stops the stage: its video is abandoned (no file), and Python hears of it at its next
//! call. What its player holds is told as it changes, so Python reads it without waiting (`held`,
//! `pressured`).

use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Condvar, Mutex, OnceLock};

use crate::CameraView;
use crate::encode::Encoder;
use crate::export::Export;
use crate::render::{Player, Upload, with_gpu};

/// Bytes queued and not yet carried out, at most (but for a call larger than that alone).
const QUEUED: usize = 256 << 20;

/// A call of Python's that the stage's thread carries out.
pub(crate) enum Call {
    Upload(Upload),
    Evict(Vec<u64>),
    /// The video's encoder: its frames follow.
    Video(Encoder),
    /// The video's next frame, shown for `repeat` frames (`key`: a keyframe): a view and its
    /// records, its cameras' views drawn first.
    Frame { view: Vec<u8>, records: Vec<u8>, cameras: Vec<CameraView>, repeat: u32, key: bool },
}

impl Call {
    /// The bytes it holds, as the queue counts them.
    fn size(&self) -> usize {
        match self {
            Call::Upload(upload) => upload.size(),
            Call::Evict(keys) => 8 * keys.len(),
            Call::Frame { view, records, cameras, .. } => view.len() + records.len() + cameras.iter().map(|c| c.3.len() + c.4.len()).sum::<usize>(),
            Call::Video(_) => 0,
        }
    }
}

/// The calls queued and not yet carried out, and the bytes they hold.
#[derive(Default)]
struct Queued {
    calls: usize,
    bytes: usize,
}

/// What Python and the stage's thread share: the player; what is queued; what stopped the stage;
/// whether it is let go of (what is queued then is dropped); what its player holds.
struct Shared {
    player: Mutex<Player>,
    queued: Mutex<Queued>,
    room: Condvar,
    fault: OnceLock<String>,
    left: AtomicBool,
    held: AtomicUsize,
    pressured: AtomicBool,
    limits: OnceLock<wgpu::Limits>, // the GPU's, once the player has drawn
}

impl Shared {
    /// Tell what the player holds, now that a call changed it.
    fn tell(&self, player: &Player) {
        self.held.store(player.held(), Ordering::Release);
        self.pressured.store(self.limits.get().is_some_and(|limits| !player.fits(limits)), Ordering::Release);
    }

    /// The GPU's limits, known from now on: the player draws.
    fn drew(&self) {
        if self.limits.get().is_none()
            && let Ok(limits) = with_gpu(|gpu| gpu.device.limits())
        {
            let _ = self.limits.set(limits);
        }
    }
}

/// The stage (see the module): a player, its thread, and the queue to it.
pub(crate) struct Stage {
    inbox: Option<Sender<Call>>,
    thread: Option<std::thread::JoinHandle<()>>,
    shared: Arc<Shared>,
}

impl Stage {
    /// A stage whose player draws `width` × `height` frames, with `samples` per pixel.
    pub(crate) fn new(width: u32, height: u32, samples: u32) -> Self {
        let (inbox, calls) = mpsc::channel();
        let shared = Arc::new(Shared {
            player: Mutex::new(Player::new(width, height, samples)),
            queued: Mutex::new(Queued::default()),
            room: Condvar::new(),
            fault: OnceLock::new(),
            left: AtomicBool::new(false),
            held: AtomicUsize::new(0),
            pressured: AtomicBool::new(false),
            limits: OnceLock::new(),
        });
        let theirs = shared.clone();
        let thread = std::thread::Builder::new().name("manimgx stage".into()).spawn(move || run(&calls, &theirs)).expect("a stage's thread");
        Self { inbox: Some(inbox), thread: Some(thread), shared }
    }

    /// Queue a call, once there is room for it; what stopped the stage, if something did.
    pub(crate) fn call(&self, call: Call) -> Result<(), String> {
        let size = call.size();
        let mut queued = self.shared.queued.lock().expect("the queue's count");
        loop {
            if let Some(fault) = self.shared.fault.get() {
                return Err(fault.clone());
            }
            if queued.calls == 0 || queued.bytes + size <= QUEUED {
                break;
            }
            queued = self.shared.room.wait(queued).expect("the queue's count");
        }
        queued.calls += 1;
        queued.bytes += size;
        drop(queued);
        self.inbox.as_ref().ok_or_else(ended)?.send(call).map_err(|_| ended())
    }

    /// Once every call queued before is carried out, `then` on the player, here: what Python
    /// waits for. What stopped the stage, if something did.
    pub(crate) fn now<T>(&self, then: impl FnOnce(&mut Player) -> Result<T, String>) -> Result<T, String> {
        let mut queued = self.shared.queued.lock().expect("the queue's count");
        loop {
            if let Some(fault) = self.shared.fault.get() {
                return Err(fault.clone());
            }
            if queued.calls == 0 {
                break;
            }
            queued = self.shared.room.wait(queued).expect("the queue's count");
        }
        drop(queued);
        let mut player = self.shared.player.lock().expect("the player");
        let done = then(&mut player);
        self.shared.drew();
        self.shared.tell(&player);
        done
    }

    /// Stop the stage for what went wrong with its video, here: the video is abandoned.
    pub(crate) fn fail(&self, error: &str) {
        self.shared.player.lock().expect("the player").export = None;
        let _ = self.shared.fault.set(error.into());
        self.shared.room.notify_all();
    }

    /// The bytes its player holds alive (`render::Player::held`), as of the calls carried out.
    pub(crate) fn held(&self) -> usize {
        self.shared.held.load(Ordering::Acquire)
    }

    /// Whether what its player holds outgrows a GPU buffer's binding, as of the calls carried out.
    pub(crate) fn pressured(&self) -> bool {
        self.shared.pressured.load(Ordering::Acquire)
    }
}

impl Drop for Stage {
    /// Let go of: what is queued is dropped, and a video not ended is abandoned.
    fn drop(&mut self) {
        self.shared.left.store(true, Ordering::Release);
        self.inbox = None;
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

fn ended() -> String {
    "the film's stage has ended".into()
}

/// The stage's thread: each call carried out as it comes, in order, until the stage is let go of.
fn run(calls: &Receiver<Call>, shared: &Shared) {
    // however the thread ends, Python stops waiting for it
    struct Leaving<'a>(&'a Shared);
    impl Drop for Leaving<'_> {
        fn drop(&mut self) {
            let _ = self.0.fault.set(ended());
            self.0.room.notify_all();
        }
    }
    let _leaving = Leaving(shared);
    for call in calls {
        let size = call.size();
        if !shared.left.load(Ordering::Acquire) && shared.fault.get().is_none() {
            let draws = matches!(call, Call::Video(_) | Call::Frame { .. });
            let mut player = shared.player.lock().expect("the player");
            if let Err(error) = carry(&mut player, call) {
                player.export = None; // abandoned: its file goes
                let _ = shared.fault.set(error);
            }
            if draws {
                shared.drew();
            }
            shared.tell(&player);
        }
        let mut queued = shared.queued.lock().expect("the queue's count");
        queued.calls -= 1;
        queued.bytes -= size;
        drop(queued);
        shared.room.notify_all();
    }
}

/// How a video was made: seconds since it began, of them in x264, the share of macroblocks
/// converted, bytes written.
pub(crate) type Made = (f64, f64, f64, u64);

/// A film's sound, as its video carries it: float32 samples, interleaved, `channels` of them, at
/// `rate` a second, encoded as AAC-LC at about `bitrate` bits a second.
pub(crate) struct Sound {
    pub(crate) samples: Vec<f32>,
    pub(crate) channels: usize,
    pub(crate) rate: u32,
    pub(crate) bitrate: u32,
}

/// The player's video written, with `sound` beside it: what it made.
pub(crate) fn end(player: &mut Player, sound: Option<Sound>) -> Result<Made, String> {
    let mut export = player.export.take().ok_or("no export is open")?;
    let audio = sound.map(|s| crate::aac::encode(&s.samples, s.channels, s.rate, s.bitrate)).transpose()?;
    with_gpu(|gpu| {
        while !export.pending.is_empty() {
            player.retire(gpu, &mut export)?;
        }
        export.finish(audio)
    })?
}

/// Carry out a call.
fn carry(player: &mut Player, call: Call) -> Result<(), String> {
    match call {
        Call::Upload(upload) => player.upload(upload),
        Call::Evict(keys) => {
            with_gpu(|gpu| player.settle(gpu))??;
            player.evict(keys);
            Ok(())
        }
        Call::Video(encoder) => {
            let (width, height) = (player.width, player.height);
            player.export = Some(with_gpu(|gpu| Export::new(gpu, encoder, width, height))??);
            Ok(())
        }
        Call::Frame { view, records, cameras, repeat, key } => {
            let frames = player.views(&view, &records, cameras)?;
            with_gpu(|gpu| player.push_frames(gpu, frames, repeat, key, None))?
        }
    }
}
