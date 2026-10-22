//! The engine as Python's extension module, `manimgx._engine`: the player (natively, on a thread
//! of its own: read back or encoded to MP4, see `stage`), the recorder of a take (everywhere), the
//! typesetter and the content keys, over the core in `render`, `take` and `typeset`.

#[cfg(feature = "render")]
use pyo3::exceptions::PyRuntimeError;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

#[cfg(feature = "render")]
use crate::render::with_gpu;
use crate::{CameraView, take};

// One source for the native binding and every Python export entry point.
const DEFAULT_ENCODER_PRESET: &str = "medium";
const DEFAULT_ENCODER_CRF: f32 = 23.0;

#[cfg(feature = "typeset")]
pyo3::create_exception!(_engine, TypstError, pyo3::exceptions::PyException);

/// The GPU's player, natively: shapes, brushes and images uploaded once under a key, then frames
/// drawn — into a video, or read back. Each call is checked here and carried out on the player's
/// own thread, in order (see `stage`): so a call waits only for room in the queue, and for what it
/// asks for (pixels, the video's end).
#[cfg(feature = "export")]
#[pyclass(module = "manimgx._engine")]
struct Player {
    stage: crate::stage::Stage,
    width: u32,
    height: u32,
}

#[cfg(feature = "export")]
impl Player {
    /// Queue an upload made from what Python sent (a mistake in it is Python's: a ValueError).
    fn upload(&self, py: Python<'_>, made: Result<crate::render::Upload, String>) -> PyResult<()> {
        let upload = made.map_err(PyValueError::new_err)?;
        self.call(py, crate::stage::Call::Upload(upload))
    }

    fn call(&self, py: Python<'_>, call: crate::stage::Call) -> PyResult<()> {
        py.detach(|| self.stage.call(call)).map_err(PyRuntimeError::new_err)
    }
}

#[cfg(feature = "export")]
#[pymethods]
impl Player {
    #[new]
    #[pyo3(signature = (width, height, samples = 4))]
    fn new(width: u32, height: u32, samples: u32) -> Self {
        Self { stage: crate::stage::Stage::new(width, height, samples), width, height }
    }

    fn add_path(&self, py: Python<'_>, key: u64, points: &[u8], subpaths: &[u8], centroid_area: [f32; 6]) -> PyResult<()> {
        self.upload(py, crate::render::Upload::path(key, points, subpaths, centroid_area))
    }

    fn add_points(&self, py: Python<'_>, key: u64, vertices: &[u8]) -> PyResult<()> {
        self.upload(py, crate::render::Upload::points(key, vertices))
    }

    #[pyo3(signature = (key, points, uvs, normals, triangles, outline = 0, block = 0))]
    #[allow(clippy::too_many_arguments)]
    fn add_mesh(&self, py: Python<'_>, key: u64, points: &[u8], uvs: &[u8], normals: &[u8], triangles: &[u8], outline: u32, block: u32) -> PyResult<()> {
        self.upload(py, crate::render::Upload::mesh(key, points, uvs, normals, triangles, outline, block))
    }

    #[pyo3(signature = (key, points, closed = false))]
    fn grow_path(&self, py: Python<'_>, key: u64, points: &[u8], closed: bool) -> PyResult<()> {
        self.upload(py, crate::render::Upload::grow(key, points, closed))
    }

    fn add_rows(&self, py: Python<'_>, key: u64, rows: &[u8]) -> PyResult<()> {
        self.upload(py, crate::render::Upload::rows(key, rows))
    }

    fn add_texture(&self, py: Python<'_>, key: u64, width: u32, height: u32, rgba: &[u8]) -> PyResult<()> {
        self.upload(py, crate::render::Upload::texture(key, width, height, rgba))
    }

    fn add_environment(&self, py: Python<'_>, id: u32, width: u32, height: u32, rgbe: &[u8]) -> PyResult<()> {
        self.upload(py, crate::render::Upload::environment(id, width, height, rgbe))
    }

    /// Forget shapes, brushes and textures, once the video's frames in flight that may draw them
    /// again are settled.
    fn evict(&self, py: Python<'_>, keys: Vec<u64>) -> PyResult<()> {
        self.call(py, crate::stage::Call::Evict(keys))
    }

    /// The bytes it holds alive (shapes, brushes, textures), as of the calls carried out.
    fn held(&self) -> usize {
        self.stage.held()
    }

    /// Whether what it holds outgrows a GPU buffer's binding (each frame then binds only what it
    /// draws), as of the calls carried out.
    fn pressured(&self) -> bool {
        self.stage.pressured()
    }

    /// Render one frame, as the calls before it left the player, and read it back: RGBA8 rows,
    /// top to bottom. `cameras` are views drawn first, each into a texture that textured meshes
    /// of later views sample by its key: (key, width, height, view, records).
    #[pyo3(signature = (view, records, cameras = Vec::new()))]
    fn render<'py>(&self, py: Python<'py>, view: &[u8], records: &[u8], cameras: Vec<CameraView>) -> PyResult<Bound<'py, PyBytes>> {
        PyBytes::new_with(py, (4 * self.width * self.height) as usize, |into| {
            py.detach(|| {
                self.stage.now(|player| {
                    let frames = player.views(view, records, cameras)?;
                    with_gpu(|gpu| player.pixels(gpu, &frames, into))?
                })
            })
            .map_err(PyRuntimeError::new_err)
        })
    }

    /// Start an MP4 at `path`; frames follow with `push`, and `end_export` writes the file. x264
    /// runs at `preset` and `crf` (the module's defaults), with `options` — its own settings
    /// over those (as `-x264-params`, e.g. `[("keyint", "600")]`).
    #[pyo3(signature = (path, fps = 60, preset = DEFAULT_ENCODER_PRESET.to_string(), crf = DEFAULT_ENCODER_CRF, options = Vec::new()))]
    fn begin_export(&self, py: Python<'_>, path: String, fps: u32, preset: String, crf: f32, options: Vec<(String, String)>) -> PyResult<()> {
        let encoder = crate::encode::Encoder::new(self.width, self.height, fps, &preset, crf, &options, &path).map_err(PyRuntimeError::new_err)?;
        self.call(py, crate::stage::Call::Video(encoder))
    }

    /// The next frame of the video, shown for `repeat` frames: a view and its records, with
    /// `cameras` drawn first (as for `render`); `key`: a keyframe, where a player can start. With
    /// `capture`, wait for its pixels and return them: the same draw's.
    #[pyo3(signature = (view, records, repeat = 1, cameras = Vec::new(), key = false, capture = false))]
    #[allow(clippy::too_many_arguments)]
    fn push<'py>(&self, py: Python<'py>, view: &[u8], records: &[u8], repeat: u32, cameras: Vec<CameraView>, key: bool, capture: bool) -> PyResult<Option<Bound<'py, PyBytes>>> {
        if !capture {
            let (view, records) = (view.to_vec(), records.to_vec());
            self.call(py, crate::stage::Call::Frame { view, records, cameras, repeat, key })?;
            return Ok(None);
        }
        let pixels = PyBytes::new_with(py, (4 * self.width * self.height) as usize, |into| {
            py.detach(|| {
                self.stage
                    .now(|player| {
                        let frames = player.views(view, records, cameras)?;
                        with_gpu(|gpu| player.push_frames(gpu, frames, repeat, key, Some(into)))?
                    })
                    .inspect_err(|error| self.stage.fail(error))
            })
            .map_err(PyRuntimeError::new_err)
        })?;
        Ok(Some(pixels))
    }

    /// Abandon the video: nothing is written (once this returns, nor is any part of it).
    fn abort_export(&self, py: Python<'_>) {
        // a player stopped by a mistake has abandoned it already
        let _ = py.detach(|| {
            self.stage.now(|player| {
                player.export = None;
                Ok(())
            })
        });
    }

    /// Finish the video, with `sound` beside it if given — its soundtrack: float32 samples,
    /// interleaved, `channels` of them, at `rate` samples a second, encoded as AAC-LC at about
    /// `bitrate` bits a second. Returns (seconds since it began, of which in x264, fraction of
    /// macroblocks converted, bytes written).
    #[pyo3(signature = (sound = None, channels = 1, rate = 48000, bitrate = 192000))]
    fn end_export(&self, py: Python<'_>, sound: Option<&[u8]>, channels: usize, rate: u32, bitrate: u32) -> PyResult<crate::stage::Made> {
        let samples: Option<Vec<f32>> = sound.map(|s| crate::read(s, "sound")).transpose().map_err(PyValueError::new_err)?;
        let sound = samples.map(|samples| crate::stage::Sound { samples, channels, rate, bitrate });
        py.detach(|| self.stage.now(|player| crate::stage::end(player, sound))).map_err(PyRuntimeError::new_err)
    }
}

/// A complete recorded take, drawn headlessly by the same decoder and player as a window.
#[cfg(feature = "player")]
#[pyclass(module = "manimgx._engine")]
struct Replay {
    take: crate::project::Take,
}

#[cfg(feature = "player")]
#[pymethods]
impl Replay {
    #[new]
    fn new(data: &[u8]) -> PyResult<Self> {
        crate::project::Take::read(data).map(|take| Self { take }).map_err(PyValueError::new_err)
    }

    #[getter]
    fn size(&self) -> (u32, u32) { self.take.size }

    #[getter]
    fn frames(&self) -> u32 { self.take.frames }

    #[getter]
    fn fps(&self) -> f64 { self.take.fps }

    #[getter]
    fn timeline(&self) -> Vec<(u32, u32)> { self.take.timeline() }

    /// A zero-based frame, in any order: RGBA8 rows, top to bottom, at the recorded size.
    fn render<'py>(&mut self, py: Python<'py>, frame: i64) -> PyResult<Bound<'py, PyBytes>> {
        if frame < 0 || frame >= self.take.frames as i64 {
            return Err(pyo3::exceptions::PyIndexError::new_err(format!("frame {frame} is outside the take's {} frames", self.take.frames)));
        }
        let frames = self.take.frame_views(frame as u32).map_err(PyValueError::new_err)?;
        let take = &mut self.take;
        let (width, height) = take.size;
        PyBytes::new_with(py, (4 * width * height) as usize, |into| {
            py.detach(|| with_gpu(|gpu| take.player.pixels(gpu, &frames, into))?).map_err(PyRuntimeError::new_err)
        })
    }
}

/// The content key of some bytes, taken as one stream: xxh3, 64 bits, never 0 (reserved). What
/// names an upload, so that equal content is uploaded once.
#[pyfunction]
#[pyo3(signature = (*parts))]
fn digest(parts: Vec<pyo3::pybacked::PyBackedBytes>) -> u64 {
    crate::digest(parts.iter().map(|p| &p[..]))
}

/// A Radiance (.hdr) file's picture (its bytes) as an environment keeps it: its width, height,
/// and RGBE pixels (a byte of red, green, blue and a shared exponent each) row by row from the
/// top, halved until no wider than 4096.
#[pyfunction]
fn read_hdr<'py>(py: Python<'py>, data: &[u8]) -> PyResult<(u32, u32, Bound<'py, PyBytes>)> {
    let (width, height, rgbe) = crate::environment::read_hdr(data).map_err(pyo3::exceptions::PyValueError::new_err)?;
    let (width, height, rgbe) = py.detach(|| crate::environment::narrowed(width, height, rgbe));
    Ok((width, height, PyBytes::new(py, &rgbe)))
}

/// A file's audio (its bytes: WAV, MP3, AAC/M4A, FLAC, Ogg Vorbis, ALAC, AIFF or CAF) at `rate`
/// samples a second: float32 samples, interleaved, and how many channels.
#[pyfunction]
fn decode_audio<'py>(py: Python<'py>, data: Vec<u8>, rate: u32) -> PyResult<(Bound<'py, PyBytes>, usize)> {
    let (samples, channels) = py
        .detach(|| {
            let (samples, from, channels) = crate::audio::decode(data)?;
            crate::audio::resample(&samples, channels, from as f64, rate as f64).map(|samples| (samples, channels))
        })
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
    Ok((PyBytes::new(py, bytemuck::cast_slice(&samples)), channels))
}

/// Interleaved float32 samples of `channels` channels at `rate` samples a second, resampled to `to`.
#[pyfunction]
fn resample_audio<'py>(py: Python<'py>, samples: &[u8], channels: usize, rate: f64, to: f64) -> PyResult<Bound<'py, PyBytes>> {
    let input: Vec<f32> = crate::read(samples, "samples").map_err(pyo3::exceptions::PyValueError::new_err)?;
    let out = py.detach(|| crate::audio::resample(&input, channels, rate, to)).map_err(pyo3::exceptions::PyValueError::new_err)?;
    Ok(PyBytes::new(py, bytemuck::cast_slice(&out)))
}

/// A take being recorded: the engine's calls — the same uploads a player takes, then frames —
/// written as the stream a player plays back (see `take`). It draws nothing.
#[pyclass(module = "manimgx._engine")]
struct Recorder {
    writer: take::Writer,
}

#[pymethods]
impl Recorder {
    /// A take of `width` × `height` frames, `fps` a second.
    #[new]
    fn new(width: u32, height: u32, fps: f64) -> Self {
        let mut writer = take::Writer::default();
        writer.start(width, height, fps);
        Self { writer }
    }

    fn add_path(&mut self, key: u64, points: &[u8], subpaths: &[u8], centroid_area: [f32; 6]) {
        self.writer.path(key, points, subpaths, centroid_area);
    }

    fn add_points(&mut self, key: u64, vertices: &[u8]) {
        self.writer.points(key, vertices);
    }

    #[pyo3(signature = (key, points, uvs, normals, triangles, outline = 0, block = 0))]
    #[allow(clippy::too_many_arguments)]
    fn add_mesh(&mut self, key: u64, points: &[u8], uvs: &[u8], normals: &[u8], triangles: &[u8], outline: u32, block: u32) -> PyResult<()> {
        crate::check_key(key).map_err(PyValueError::new_err)?;
        let mesh = crate::mesh::Mesh::new(points, uvs, normals, triangles, outline, block).map_err(PyValueError::new_err)?;
        self.writer.mesh(key, &mesh);
        Ok(())
    }

    fn add_rows(&mut self, key: u64, rows: &[u8]) {
        self.writer.rows(key, rows);
    }

    fn add_texture(&mut self, key: u64, width: u32, height: u32, rgba: &[u8]) {
        self.writer.texture(key, width, height, rgba);
    }

    fn add_environment(&mut self, id: u32, width: u32, height: u32, rgbe: &[u8]) {
        self.writer.environment(id, width, height, rgbe);
    }

    #[pyo3(signature = (key, points, closed = false))]
    fn grow_path(&mut self, key: u64, points: &[u8], closed: bool) {
        self.writer.grow(key, points, closed);
    }

    /// Nothing: a take keeps the uploads its frames need itself (its player holds what it draws).
    fn evict(&mut self, keys: Vec<u64>) {
        let _ = keys;
    }

    /// 0: a take holds nothing on a GPU.
    fn held(&self) -> usize {
        0
    }

    /// The next frame, shown for `repeat` frames: a view and its records, `cameras` drawn first
    /// (as for a player's `render`).
    #[pyo3(signature = (view, records, repeat = 1, cameras = Vec::new()))]
    fn frame(&mut self, view: &[u8], records: &[u8], repeat: u32, cameras: Vec<CameraView>) {
        self.writer.frame(view, records, repeat, &cameras);
    }

    /// A note for whoever shows the take (JSON: a play that ended, a section, the captions).
    fn note(&mut self, json: &str) {
        self.writer.note(json);
    }

    /// The film's sound: an audio file, which the player plays beside the frames.
    fn sound(&mut self, file: &[u8]) {
        self.writer.sound(file);
    }

    /// The take's end: its film ended, or (`failed`) its scene failed.
    #[pyo3(signature = (failed = false))]
    fn end(&mut self, failed: bool) {
        self.writer.close(failed);
    }

    /// What has been recorded since the last drain.
    fn drain<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.writer.drain())
    }
}

/// A note on its own: a message of the take stream belonging to no take (the director's word
/// between takes: the file's scenes, an error).
#[pyfunction]
fn note<'py>(py: Python<'py>, json: &str) -> Bound<'py, PyBytes> {
    let mut writer = take::Writer::default();
    writer.note(json);
    PyBytes::new(py, &writer.drain())
}

/// The player for a page (see `web`), this engine built for the browser (build.rs): wasm-bindgen's
/// JS and the WebAssembly it loads; None if it was built without it (no wasm32-unknown-unknown
/// target).
#[pyfunction]
fn web() -> Option<(&'static str, &'static [u8])> {
    #[cfg(web_player)]
    return Some((
        include_str!(concat!(env!("OUT_DIR"), "/engine.js")),
        include_bytes!(concat!(env!("OUT_DIR"), "/engine_bg.wasm")),
    ));
    #[cfg(not(web_player))]
    None
}

#[cfg(feature = "typeset")]
mod typesetting {
    use pyo3::prelude::*;
    use pyo3::types::PyBytes;

    use super::TypstError;
    use crate::typeset as core;

    #[pyfunction]
    pub(super) fn cache_directory() -> Option<std::path::PathBuf> {
        core::cache_directory()
    }

    /// A typeset document: its rows (float64), its shapes' cubic points, its labelled groups, and
    /// whether it needed the system's fonts.
    type Layout = (Py<PyBytes>, Vec<Py<PyBytes>>, Vec<(String, Vec<usize>)>, bool, Vec<String>);

    /// Typeset `source` with the fonts in `font_paths` and Typst's own (a system font only by its
    /// family's name), and the packages under `packages` besides mitex's (the engine's own): its
    /// items (one row of `ROW` floats each, in document order), its shapes' cubic points and its
    /// labelled groups (a label and the items inside, nested ones too).
    #[pyfunction]
    #[pyo3(signature = (source, font_paths, packages=None, *, revision=0))]
    pub(super) fn typeset(py: Python<'_>, source: String, font_paths: Vec<String>, packages: Option<String>, revision: u64) -> PyResult<Layout> {
        let (rows, shapes, labels, system, missing) = py.detach(|| core::typeset(source, &font_paths, packages.as_deref(), revision)).map_err(TypstError::new_err)?;
        let rows = PyBytes::new(py, bytemuck::cast_slice(&rows)).unbind();
        let shapes = shapes.iter().map(|s| PyBytes::new(py, bytemuck::cast_slice(s)).unbind()).collect();
        Ok((rows, shapes, labels, system, missing))
    }

    /// The system's fonts' fingerprint (every file under their directories: path, size, time), once
    /// per process: a layout set with system fonts is good while it is unchanged.
    #[pyfunction]
    pub(super) fn system_fonts_fingerprint() -> u64 {
        core::system_fonts_fingerprint()
    }

    /// The fonts a player's face is set in: the font files in `dirs` (ManimGX's), and Typst's
    /// monospace one; each file's bytes (what the player in a page is given, see `web`).
    #[pyfunction]
    pub(super) fn face_fonts(py: Python<'_>, dirs: Vec<String>) -> Vec<Bound<'_, PyBytes>> {
        core::face_fonts(&dirs).into_iter().map(|data| PyBytes::new(py, data)).collect()
    }

    /// Each key's outline as cubic points (font units, y up); empty for a glyph with no outline
    /// (a space) or one Typst would draw as an image (a color emoji).
    #[pyfunction]
    pub(super) fn glyph_outlines(py: Python<'_>, keys: Vec<u64>) -> Vec<Py<PyBytes>> {
        core::glyph_outlines(&keys).iter().map(|points| PyBytes::new(py, bytemuck::cast_slice(points)).unbind()).collect()
    }

    /// A ligature glyph's caret positions (font units), from the font's GDEF ligature caret list;
    /// empty when the font gives none (then a glyph is divided equally among what it draws).
    #[pyfunction]
    pub(super) fn ligature_carets(key: u64) -> Vec<f64> {
        core::ligature_carets(key)
    }

    /// Where `text`'s graphemes (user-perceived characters, UAX #29) start, in characters.
    #[pyfunction]
    pub(super) fn graphemes(text: &str) -> Vec<usize> {
        core::graphemes(text)
    }

    /// Where Unicode lets `text` break, in characters from 0 to its length: where a line may
    /// break (UAX #14) and where a sentence ends (UAX #29).
    #[pyfunction]
    pub(super) fn segments(text: &str) -> (Vec<usize>, Vec<usize>) {
        core::segments(text)
    }

    /// LaTeX math as Typst math (mitex's conversion; its default command spec).
    #[pyfunction]
    pub(super) fn mitex_math(latex: &str) -> PyResult<String> {
        core::mitex_math(latex).map_err(TypstError::new_err)
    }

    /// LaTeX text as Typst markup (mitex's conversion; its default command spec).
    #[pyfunction]
    pub(super) fn mitex_text(latex: &str) -> PyResult<String> {
        core::mitex_text(latex).map_err(TypstError::new_err)
    }
}

/// The GPU's warm-up, once begun (`start_gpu`): the process that began it, and a channel that
/// closes when it is done.
#[cfg(feature = "render")]
static WARMING: std::sync::OnceLock<(u32, std::sync::Mutex<std::sync::mpsc::Receiver<()>>)> = std::sync::OnceLock::new();

/// Starts bringing the GPU up, on a thread of its own, unless that has begun; whether this call
/// began it. What draws first waits for it. A process that will draw says so as early as it
/// knows (a film that draws, the command line's drawing commands), so the GPU comes up while
/// the rest loads; one that never draws never brings it up.
#[cfg(feature = "render")]
#[pyfunction]
fn start_gpu() -> bool {
    let mut began = false;
    WARMING.get_or_init(|| {
        began = true;
        let (done, warming) = std::sync::mpsc::channel::<()>();
        std::thread::spawn(move || {
            let _ = with_gpu(|_| ());
            drop(done);
        });
        (std::process::id(), std::sync::Mutex::new(warming))
    });
    began
}

/// The adapter actually used by this engine, after bringing it up if necessary. Diagnostic
/// consumers can distinguish renderer changes from a different backend, device or driver.
#[cfg(feature = "player")]
#[pyfunction]
fn adapter_info(py: Python<'_>) -> PyResult<std::collections::BTreeMap<String, String>> {
    let info = py.detach(|| with_gpu(|gpu| gpu.adapter.get_info())).map_err(PyRuntimeError::new_err)?;
    Ok([
        ("name", info.name),
        ("vendor", info.vendor.to_string()),
        ("device", info.device.to_string()),
        ("device_type", format!("{:?}", info.device_type)),
        ("driver", info.driver),
        ("driver_info", info.driver_info),
        ("backend", format!("{:?}", info.backend)),
    ].into_iter().map(|(key, value)| (key.to_string(), value)).collect())
}

/// Waits for the GPU's warm-up, at most 30 s; Python calls it as it exits. Exit unloads the
/// drivers, and must not unload one still starting on the warm-up's thread: lavapipe crashed a
/// process that loaded the engine and exited at once. A forked child has no warm-up to wait for.
#[cfg(feature = "render")]
#[pyfunction]
fn settle(py: Python<'_>) {
    if let Some((process, warming)) = WARMING.get()
        && *process == std::process::id()
    {
        py.detach(|| warming.lock().map(|warming| warming.recv_timeout(std::time::Duration::from_secs(30))).ok());
    }
}

/// Open ManimGX's player in a window on this machine's screen, playing the takes that come on
/// standard input (see `window`), until the window is closed or its input ends. It starts at
/// `time` seconds; its text is set in the fonts under `fonts`.
#[cfg(feature = "window")]
#[pyfunction]
#[pyo3(signature = (title, time = 0.0, fonts = Vec::new()))]
fn window(py: Python<'_>, title: String, time: f64, fonts: Vec<String>) -> PyResult<()> {
    py.detach(|| crate::window::run(crate::window::Options { title, time, fonts })).map_err(PyRuntimeError::new_err)
}

#[pymodule]
fn _engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("DEFAULT_ENCODER_PRESET", DEFAULT_ENCODER_PRESET)?;
    m.add("DEFAULT_ENCODER_CRF", DEFAULT_ENCODER_CRF)?;
    m.add("TAKE_VERSION", take::VERSION)?;
    #[cfg(feature = "export")]
    m.add_class::<Player>()?;
    #[cfg(feature = "render")]
    {
        m.add_function(wrap_pyfunction!(start_gpu, m)?)?;
        m.py().import("atexit")?.call_method1("register", (wrap_pyfunction!(settle, m)?,))?;
    }
    #[cfg(feature = "window")]
    m.add_function(wrap_pyfunction!(window, m)?)?;
    #[cfg(feature = "player")]
    {
        m.add_class::<Replay>()?;
        m.add_function(wrap_pyfunction!(adapter_info, m)?)?;
    }
    m.add_class::<Recorder>()?;
    m.add_function(wrap_pyfunction!(note, m)?)?;
    m.add_function(wrap_pyfunction!(web, m)?)?;
    m.add_function(wrap_pyfunction!(digest, m)?)?;
    m.add_function(wrap_pyfunction!(decode_audio, m)?)?;
    m.add_function(wrap_pyfunction!(read_hdr, m)?)?;
    m.add_function(wrap_pyfunction!(resample_audio, m)?)?;
    #[cfg(feature = "typeset")]
    {
        use typesetting::*;
        m.add_function(wrap_pyfunction!(cache_directory, m)?)?;
        m.add_function(wrap_pyfunction!(typeset, m)?)?;
        m.add_function(wrap_pyfunction!(glyph_outlines, m)?)?;
        m.add_function(wrap_pyfunction!(ligature_carets, m)?)?;
        m.add_function(wrap_pyfunction!(graphemes, m)?)?;
        m.add_function(wrap_pyfunction!(segments, m)?)?;
        m.add_function(wrap_pyfunction!(mitex_math, m)?)?;
        m.add_function(wrap_pyfunction!(mitex_text, m)?)?;
        m.add_function(wrap_pyfunction!(system_fonts_fingerprint, m)?)?;
        m.add_function(wrap_pyfunction!(face_fonts, m)?)?;
        m.add("TypstError", m.py().get_type::<TypstError>())?;
    }
    Ok(())
}
