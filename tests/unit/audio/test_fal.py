"""fal.ai's models speak a text: `Fal(model, **settings)` asks fal for it and downloads the
audio.

- A model is asked at its endpoint with the key, its text in the model's own input, the settings
  given (over what ManimGX sends unless told otherwise), and what the model is always sent; what
  it says is the audio at the URL fal answers with.
- A model's settings and their values are its own: a type checker refuses another model's, and
  a value the model doesn't take.
- A voice is named by its model and its settings, however they were written, never by its key;
  without a key, it says where to get one.
- A model's timing of its text times the words; timing that runs backwards, or none, leaves
  them estimated.
- A scene with no voice speaks through fal's default model.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

import manimgx as m
from manimgx.audio import fal
from manimgx.audio import sound as voices
from manimgx.audio.fal import Fal

AUDIO_URL = "https://v3b.fal.media/files/b/speech.wav"
SECOND_TENTH = 4800  # samples: a tenth of a second at the film's rate


class Service:
    """fal, faked: answers a model's request with an audio file's URL (and whatever else
    `reply` holds), and that URL with a tenth of a second of sound."""

    def __init__(self, reply: dict[str, object] | None = None) -> None:
        self.reply = reply or {}
        self.asked: list[
            tuple[str, dict[str, object] | None, dict[str, str] | None]
        ] = []

    def __call__(
        self,
        url: str,
        body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        self.asked.append((url, body, headers))
        if body is None:
            return voices._wav(np.full((SECOND_TENTH, 1), 0.1, np.float32))
        return json.dumps({"audio": {"url": AUDIO_URL}, **self.reply}).encode()

    @property
    def body(self) -> dict[str, object] | None:
        """What the first request sent."""
        return self.asked[0][1]


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> Service:
    fake = Service()
    monkeypatch.setattr(fal, "_fetch", fake)
    monkeypatch.setenv("FAL_KEY", "k")
    return fake


def written_otherwise(settings: dict[str, object]) -> dict[str, object]:
    """The same settings, every dict's keys in the other order."""
    return {
        k: written_otherwise(v) if isinstance(v, dict) else v
        for k, v in reversed(settings.items())
    }


models = st.sampled_from(sorted(fal._MODELS))
# `Fal` for a model drawn at run time: no type checker reads the settings it is given
untyped = cast("Callable[..., Fal]", Fal)


def settings_of(model: fal.Model) -> st.SearchStrategy[dict[str, object]]:
    """Any settings a model's schema allows."""
    return cast(
        "st.SearchStrategy[dict[str, object]]",
        st.from_type(fal._MODELS[model].settings),
    )


class TestAsking:
    @given(model=models, data=st.data(), text=st.text(min_size=1))
    def test_a_model_is_asked_for_its_text(
        self, model: fal.Model, data: st.DataObject, text: str
    ) -> None:
        spec = fal._MODELS[model]
        settings = data.draw(settings_of(model), label="settings")
        fake = Service()
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(fal, "_fetch", fake)
            speech = untyped(model, key="k", **settings)(text)
        (url, body, headers), (audio_url, nothing, _) = fake.asked
        assert url == f"https://fal.run/{model}"
        assert headers == {"Authorization": "Key k"}
        # what ManimGX sends unless told otherwise, the settings over it, what is always sent
        assert body == {
            **dict(spec.defaults),
            **settings,
            **dict(spec.fixed),
            spec.text: text,
        }
        assert (audio_url, nothing) == (AUDIO_URL, None)
        assert speech.text == text
        assert speech.duration == pytest.approx(0.1)

    def test_a_type_checker_knows_each_models_settings(self) -> None:
        # the suppressions are the test: `just check` fails if one goes unused
        others = Fal("google/gemini-3.8-flash-tts", stability=0.5)  # ty: ignore[invalid-argument-type]
        nobody = Fal("google/gemini-3.8-flash-tts", voice="Nobody")  # ty: ignore[no-matching-overload]
        # a voice keeps what it is given: its type is the check
        assert others.settings == {"stability": 0.5}
        assert nobody.settings == {"voice": "Nobody"}

    def test_without_a_key_it_says_where_to_get_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FAL_KEY", raising=False)
        with pytest.raises(RuntimeError, match="FAL_KEY"):
            Fal()("hello")

    def test_a_key_given_is_used_over_the_environments(self, service: Service) -> None:
        Fal(key="given")("hello")
        assert service.asked[0][2] == {"Authorization": "Key given"}


class TestNaming:
    @given(model=models, data=st.data(), key=st.text(min_size=1))
    def test_a_voice_is_named_by_its_model_and_settings_never_its_key(
        self, model: fal.Model, data: st.DataObject, key: str
    ) -> None:
        settings = data.draw(settings_of(model), label="settings")
        other = data.draw(settings_of(model), label="other settings")
        voice = untyped(model, key=key, **settings)
        again = untyped(model, **written_otherwise(settings))
        assert voices._identity(voice) == voices._identity(again)
        assert repr(voice) == repr(again)
        assert voice == again
        same = json.dumps(other, sort_keys=True) == json.dumps(settings, sort_keys=True)
        named = voices._identity(untyped(model, **other))
        assert (named == voices._identity(voice)) == same
        for another in fal._MODELS.keys() - {model}:
            assert voices._identity(Fal(another)) != voices._identity(voice)


class TestTiming:
    TEXT = "hi you"

    def spoken(
        self, service: Service, stamps: object
    ) -> tuple[tuple[str, float, float], ...]:
        service.reply = {"timestamps": stamps}
        speech = Fal()(self.TEXT)
        return tuple((w.text, w.start, w.end) for w in speech.words)

    def test_elevenlabs_alignment_times_the_words(self, service: Service) -> None:
        alignment = {
            "characters": list(self.TEXT),
            "character_start_times_seconds": [i / 100 for i in range(len(self.TEXT))],
            "character_end_times_seconds": [
                (i + 1) / 100 for i in range(len(self.TEXT))
            ],
        }
        assert self.spoken(service, [alignment]) == (
            ("hi", 0.0, pytest.approx(0.02)),
            ("you", pytest.approx(0.03), pytest.approx(0.06)),
        )

    def test_timed_words_time_the_words(self, service: Service) -> None:
        items = [
            {"text": "hi", "start": 0.0, "end": 0.02},
            {"text": "you", "start": 0.03, "end": 0.06},
        ]
        assert self.spoken(service, items) == (
            ("hi", 0.0, 0.02),
            ("you", 0.03, 0.06),
        )

    @pytest.mark.parametrize(
        "stamps",
        [
            None,
            [],
            [
                {"text": "hi", "start": 0.05, "end": 0.07},
                {"text": "you", "start": 0.0, "end": 0.02},
            ],
            [{"text": "bye", "start": 0.0, "end": 0.02}],
            [{"text": "hi you", "start": 0.05, "end": 0.0}],
            [{"text": "hi you", "start": -0.05, "end": 0.02}],
            [{"text": "hi you", "start": 0.0, "end": float("inf")}],
            [{"text": "hi you", "start": 0.0, "end": float("nan")}],
        ],
        ids=[
            "none",
            "empty",
            "backwards",
            "other words",
            "negative duration",
            "negative start",
            "infinite end",
            "nan end",
        ],
    )
    def test_without_usable_timing_the_words_are_estimated(
        self, service: Service, stamps: object
    ) -> None:
        words = self.spoken(service, stamps)
        assert [w for w, _, _ in words] == ["hi", "you"]
        assert all(0 <= a <= b <= 0.1 + 1e-9 for _, a, b in words)


class TestScene:
    def test_a_scene_without_a_voice_speaks_through_fals_default(
        self, service: Service, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr("manimgx.scene._voice_folder", lambda scene: tmp_path)

        class Narrated(m.Scene):
            def construct(self) -> None:
                self.say("hello there")

        (clip,) = Narrated().render().clips
        assert service.asked[0][0] == "https://fal.run/fal-ai/elevenlabs/tts/eleven-v3"
        assert clip.sound.duration == pytest.approx(0.1)
