from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts"
MODEL_PATH = ARTIFACT_DIR / "emotion_model.joblib"
METRICS_PATH = ARTIFACT_DIR / "metrics.json"
SETTINGS_PATH = ARTIFACT_DIR / "settings.json"
SETTINGS_VERSION = 2

LABEL_SAFE = "safe"
LABEL_CAUTION = "caution"
LABEL_HIGH_RISK = "high_risk"

PROFANITY = {"damn", "hell", "stupid", "idiot", "useless", "hate", "shut up", "fuck", "shit"}
INTENSIFIERS = {"always", "never", "literally", "seriously", "obviously", "totally"}
SARCASM_MARKERS = {"yeah right", "sure", "fine", "whatever", "/s"}
URGENT_PATTERNS = {"asap", "immediately", "right now", "today", "now"}
EMPATHY_MARKERS = {"i feel", "i want", "can we", "please", "understand", "talk this through"}
SEVERE_PATTERNS = {
    r"\bfuck off\b": "I need space right now",
    r"\bfuckoff\b": "I need space right now",
    r"\bf\W*ck\W*off\b": "I need space right now",
    r"\bfuck you\b": "I am very upset right now",
    r"\bgo away\b": "I need distance right now",
    r"\bleave me alone\b": "I need some space before continuing",
    r"\byou are impossible\b": "this feels very hard for me to handle",
    r"\byou are the problem\b": "this situation is hurting me",
}
RELATIONSHIP_PATTERNS = {
    "partner": {"tone": "personal", "opener": "I care about us, so I want to say this more clearly: "},
    "friend": {"tone": "personal", "opener": "I value our friendship, so I want to say this more calmly: "},
    "teammate": {"tone": "professional", "opener": "I want to keep this constructive, so here is a calmer version: "},
    "manager": {"tone": "professional", "opener": "I want to explain this professionally and clearly: "},
}

SUPPORTED_INTEGRATIONS = [
    {
        "id": "whatsapp",
        "name": "WhatsApp Web",
        "category": "messaging",
        "host_patterns": ["https://web.whatsapp.com/*"],
        "supported_content": ["chat", "group_chat"],
        "notes": "Intercepts chat compose boxes before Enter sends a message.",
        "launch_url": "https://web.whatsapp.com/",
    },
    {
        "id": "instagram",
        "name": "Instagram DMs",
        "category": "social",
        "host_patterns": ["https://www.instagram.com/*"],
        "supported_content": ["chat", "comment"],
        "notes": "Covers direct messages and comment boxes on the web client.",
        "launch_url": "https://www.instagram.com/direct/inbox/",
    },
    {
        "id": "gmail",
        "name": "Gmail",
        "category": "email",
        "host_patterns": ["https://mail.google.com/*"],
        "supported_content": ["email", "reply"],
        "notes": "Applies stronger delay defaults to send flows with longer-form email text.",
        "launch_url": "https://mail.google.com/",
    },
    {
        "id": "google_docs",
        "name": "Google Docs",
        "category": "documents",
        "host_patterns": ["https://docs.google.com/*"],
        "supported_content": ["document", "comment"],
        "notes": "Flags reactive comments and revision notes before they are submitted.",
        "launch_url": "https://docs.google.com/",
    },
    {
        "id": "generic",
        "name": "Any Website",
        "category": "universal",
        "host_patterns": ["<all_urls>"],
        "supported_content": ["chat", "comment", "email", "document", "search"],
        "notes": "Fallback scanning for any editable element the extension detects.",
        "launch_url": "https://www.google.com/",
    },
]


@dataclass
class AnalysisResult:
    label: str
    confidence: float
    cooldown_seconds: int
    reasoning: list[str]
    rewritten_message: str
    can_send_now: bool
    model_accuracy: float
    source_app: str
    content_type: str
    delay_mode: str
    risk_score: int
    send_action: str
    blocked_features: list[str]


def _default_settings() -> dict:
    return {
        "version": SETTINGS_VERSION,
        "default_delay_mode": "smart",
        "linked_apps": [
            {"id": item["id"], "enabled": False, "delay_mode": "smart"}
            for item in SUPPORTED_INTEGRATIONS
        ],
    }


def load_settings() -> dict:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    if not SETTINGS_PATH.exists():
        settings = _default_settings()
        SETTINGS_PATH.write_text(json.dumps(settings, indent=2))
        return settings
    try:
        settings = json.loads(SETTINGS_PATH.read_text())
    except Exception:
        settings = _default_settings()
        SETTINGS_PATH.write_text(json.dumps(settings, indent=2))
        return settings
    if (
        settings.get("version") != SETTINGS_VERSION
        or "default_delay_mode" not in settings
        or "linked_apps" not in settings
    ):
        settings = _default_settings()
        SETTINGS_PATH.write_text(json.dumps(settings, indent=2))
    return settings


def save_settings(settings: dict) -> dict:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    settings["version"] = SETTINGS_VERSION
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2))
    return settings


def _normalize_text(text: str) -> str:
    normalized = text.strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"([!?.,])\1+", r"\1", normalized)
    return normalized


def _contains_profanity(message: str) -> bool:
    lowered = _normalize_text(message)
    compact = re.sub(r"[\s\W_]+", "", lowered)
    if any(word in lowered for word in PROFANITY):
        return True
    if any(token in compact for token in {"fuckoff", "fuckyou", "fucking", "bullshit", "shit"}):
        return True
    if re.search(r"f\W*u\W*c\W*k", lowered):
        return True
    return False


def _has_severe_phrase(message: str) -> bool:
    lowered = _normalize_text(message)
    compact = re.sub(r"[\s\W_]+", "", lowered)
    if "fuckoff" in compact:
        return True
    return any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in SEVERE_PATTERNS)


def _generate_dataset() -> tuple[list[str], list[str]]:
    safe_templates = [
        "Thanks for handling that earlier.",
        "Can we talk about this when you have a minute?",
        "I disagree, but I want to understand your point.",
        "I feel frustrated and want to solve this calmly.",
        "Please send me the update when you can.",
        "I need some space before I reply in detail.",
        "Let's revisit this tomorrow with a clear head.",
        "I appreciate what you did, even if I'm still upset.",
        "Could you explain what happened from your side?",
        "I want to be honest without making this worse.",
    ]
    caution_templates = [
        "I'm annoyed about what happened and need you to listen.",
        "That comment really bothered me.",
        "I am trying not to overreact, but this hurt.",
        "I don't like the way this is going.",
        "You keep missing the point and it's frustrating.",
        "This feels disrespectful and I'm upset.",
        "Maybe I'm reading this wrong, but it sounded rude.",
        "I'm angry, though I still want to fix it.",
        "Please stop brushing this off like it is nothing.",
        "I need you to take this seriously before I get even more upset.",
    ]
    high_risk_templates = [
        "You never listen and I'm done with this.",
        "I can't stand how useless this conversation is.",
        "Leave me alone if this is how you're going to act.",
        "This is exactly why nobody trusts you.",
        "I hate how you always ruin everything.",
        "Don't talk to me again until you figure yourself out.",
        "You are impossible and I'm sick of your excuses.",
        "What the hell is wrong with you?",
        "I'm done being nice about this.",
        "You always make everything worse.",
    ]
    prefixes = [
        "",
        "Honestly, ",
        "Right now, ",
        "After today, ",
        "If I'm being real, ",
        "Look, ",
    ]
    suffixes = [
        "",
        " Please think about that.",
        " I needed to say it.",
        " and I'm not hiding it.",
        " because this keeps happening.",
        " if that even matters to you.",
    ]
    relation_bits = [
        "",
        " with my friend",
        " with my partner",
        " with my teammate",
        " in our chat",
        " after that meeting",
    ]
    samples: list[str] = []
    labels: list[str] = []
    for label, templates in (
        (LABEL_SAFE, safe_templates),
        (LABEL_CAUTION, caution_templates),
        (LABEL_HIGH_RISK, high_risk_templates),
    ):
        for template in templates:
            for prefix in prefixes:
                for suffix in suffixes:
                    for relation in relation_bits:
                        text = f"{prefix}{template}{relation}{suffix}".strip()
                        if label != LABEL_SAFE:
                            samples.append(text.upper())
                            labels.append(label)
                        if label == LABEL_CAUTION:
                            samples.append(f"{text} ... maybe I'm overthinking, but still.")
                            labels.append(label)
                        if label == LABEL_HIGH_RISK:
                            samples.append(f"{text} Yeah right, like you even care.")
                            labels.append(label)
                            samples.append(f"{text} Whatever.")
                            labels.append(label)
                        samples.append(text)
                        labels.append(label)
    return samples, labels


def _build_pipeline(analyzer: str, ngram_range: tuple[int, int]) -> Pipeline:
    return Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    preprocessor=_normalize_text,
                    analyzer=analyzer,
                    ngram_range=ngram_range,
                    min_df=1,
                    sublinear_tf=True,
                ),
            ),
            (
                "classifier",
                LogisticRegression(
                    max_iter=2500,
                    class_weight="balanced",
                ),
            ),
        ]
    )


def train_and_persist_model() -> dict:
    texts, labels = _generate_dataset()
    x_train, x_test, y_train, y_test = train_test_split(
        texts,
        labels,
        test_size=0.22,
        random_state=42,
        stratify=labels,
    )
    word_pipeline = _build_pipeline("word", (1, 2))
    char_pipeline = _build_pipeline("char_wb", (3, 5))
    word_pipeline.fit(x_train, y_train)
    char_pipeline.fit(x_train, y_train)
    word_probabilities = word_pipeline.predict_proba(x_test)
    char_probabilities = char_pipeline.predict_proba(x_test)
    blended_probabilities = (word_probabilities * 0.55) + (char_probabilities * 0.45)
    classes = [str(label) for label in word_pipeline.classes_]
    predictions = [classes[index] for index in blended_probabilities.argmax(axis=1)]
    accuracy = accuracy_score(y_test, predictions)
    metrics = {
        "accuracy": round(float(accuracy), 4),
        "test_samples": len(y_test),
        "training_samples": len(y_train),
        "label_distribution": dict(Counter(labels)),
        "report": classification_report(y_test, predictions, output_dict=True),
        "model_type": "hybrid_word_char_tfidf_logistic",
        "integration_count": len(SUPPORTED_INTEGRATIONS),
    }
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    temp_model = MODEL_PATH.with_suffix(".tmp")
    temp_metrics = METRICS_PATH.with_suffix(".tmp")
    joblib.dump(
        {
            "word_pipeline": word_pipeline,
            "char_pipeline": char_pipeline,
            "weights": {"word": 0.55, "char": 0.45},
            "classes": classes,
        },
        temp_model,
    )
    temp_model.replace(MODEL_PATH)
    temp_metrics.write_text(json.dumps(metrics, indent=2))
    temp_metrics.replace(METRICS_PATH)
    return metrics


def _load_assets() -> tuple[dict, dict]:
    if not MODEL_PATH.exists() or not METRICS_PATH.exists():
        train_and_persist_model()
    try:
        pipeline = joblib.load(MODEL_PATH)
        metrics = json.loads(METRICS_PATH.read_text())
        expected_keys = {"word_pipeline", "char_pipeline", "weights", "classes"}
        if not isinstance(pipeline, dict) or not expected_keys.issubset(pipeline):
            raise ValueError("Outdated model artifact")
    except Exception:
        metrics = train_and_persist_model()
        pipeline = joblib.load(MODEL_PATH)
    return pipeline, metrics


def _cooldown_for(
    message: str,
    label: str,
    confidence: float,
    source_app: str,
    content_type: str,
    delay_mode: str,
) -> int:
    lowered = message.lower()
    exclamations = message.count("!")
    uppercase_ratio = sum(1 for char in message if char.isupper()) / max(len(message), 1)
    has_profanity = _contains_profanity(message)
    has_severe = _has_severe_phrase(message)
    base = {LABEL_SAFE: 0, LABEL_CAUTION: 30, LABEL_HIGH_RISK: 120}[label]
    if exclamations >= 2:
        base += 20
    if uppercase_ratio > 0.25:
        base += 20
    if has_profanity:
        base += 40
    if has_severe:
        base += 60
    if confidence > 0.9 and label != LABEL_SAFE:
        base += 15
    if source_app in {"gmail", "google_docs"}:
        base += 30
    if content_type in {"email", "document"}:
        base += 25
    if any(pattern in lowered for pattern in URGENT_PATTERNS):
        base += 15
    mode_adjustment = {"off": -999, "light": -20, "smart": 0, "strict": 45}.get(delay_mode, 0)
    return max(0, base + mode_adjustment)


def _risk_score(message: str, label: str, confidence: float, source_app: str, content_type: str) -> int:
    lowered = message.lower()
    score = int(round(confidence * 55))
    score += {LABEL_SAFE: 5, LABEL_CAUTION: 22, LABEL_HIGH_RISK: 38}[label]
    score += min(message.count("!"), 4) * 4
    score += 8 if _contains_profanity(message) else 0
    score += 18 if _has_severe_phrase(message) else 0
    score += 5 if any(marker in lowered for marker in SARCASM_MARKERS) else 0
    score += 7 if source_app in {"gmail", "google_docs"} else 0
    score += 5 if content_type in {"email", "document"} else 0
    score -= 8 if any(marker in lowered for marker in EMPATHY_MARKERS) else 0
    return max(0, min(100, score))


def _anger_level(risk_score: int) -> str:
    if risk_score >= 80:
        return "high"
    if risk_score >= 45:
        return "medium"
    return "low"


def _blocked_features(label: str, cooldown_seconds: int, delay_mode: str) -> list[str]:
    blocked: list[str] = []
    if label == LABEL_HIGH_RISK:
        blocked.append("instant_send")
    if cooldown_seconds > 0:
        blocked.append("send_until_cooldown_finishes")
    if delay_mode == "strict":
        blocked.append("quick_submit_shortcut")
    return blocked


def _send_action(label: str, cooldown_seconds: int) -> str:
    if label == LABEL_HIGH_RISK:
        return "rewrite_before_send"
    if cooldown_seconds > 0:
        return "hold_then_review"
    return "send_ready"


def _platform_guidance(source_app: str, content_type: str) -> str:
    app_label = {
        "whatsapp": "WhatsApp message",
        "instagram": "Instagram message",
        "gmail": "email draft",
        "google_docs": "document comment",
        "generic": "draft",
    }.get(source_app, "draft")
    return f"CalmSend is treating this as a {app_label} in the {content_type} workflow."


def _reasoning_for(
    message: str,
    label: str,
    confidence: float,
    source_app: str,
    content_type: str,
    delay_mode: str,
) -> list[str]:
    lowered = message.lower()
    reasons: list[str] = [_platform_guidance(source_app, content_type)]
    if delay_mode != "smart":
        reasons.append(f"Delay mode is set to {delay_mode}, which changes how aggressively sends are held.")
    if label == LABEL_SAFE:
        reasons.append("The message stays mostly solution-focused and measured.")
    if label == LABEL_CAUTION:
        reasons.append("The wording shows frustration that could escalate in a live chat.")
    if label == LABEL_HIGH_RISK:
        reasons.append("The wording includes blame-heavy or hostile phrasing.")
    if any(marker in lowered for marker in SARCASM_MARKERS):
        reasons.append("Possible sarcasm marker detected, which often hides stronger intent.")
    if any(word in lowered for word in INTENSIFIERS):
        reasons.append("Intensifier words raise the chance of emotional escalation.")
    if _contains_profanity(message):
        reasons.append("Profanity or insulting language increases delivery risk.")
    if "?" in message and "!" in message:
        reasons.append("Mixed punctuation suggests reactive rather than reflective phrasing.")
    if source_app in {"gmail", "google_docs"}:
        reasons.append("Long-form writing channels get stricter review because the impact is harder to undo.")
    reasons.append(f"Model confidence is {confidence:.0%}.")
    return reasons


def _rewrite_message(message: str, recipient: str, label: str, source_app: str) -> str:
    cleaned = re.sub(r"\s+", " ", message.strip())
    softened = cleaned
    replacements = {
        r"\byou never\b": "I feel unheard when this happens",
        r"\byou always\b": "this keeps happening and it affects me",
        r"\bi hate\b": "I am really upset about",
        r"\bwhat the hell\b": "I am struggling to understand",
        r"\bshut up\b": "please let me finish",
        r"\buseless\b": "unhelpful",
        r"\bstupid\b": "frustrating",
        r"\bidiot\b": "person",
        r"\bfuck\b": "deeply",
        r"\bshit\b": "situation",
        r"\bdamn\b": "really",
        r"\bhell\b": "difficult moment",
    }
    for pattern, replacement in SEVERE_PATTERNS.items():
        softened = re.sub(pattern, replacement, softened, flags=re.IGNORECASE)
    for pattern, replacement in replacements.items():
        softened = re.sub(pattern, replacement, softened, flags=re.IGNORECASE)
    softened = re.sub(r"f\W*u\W*c\W*k\W*off", "I need space right now", softened, flags=re.IGNORECASE)
    softened = re.sub(r"\bfuckoff\b", "I need space right now", softened, flags=re.IGNORECASE)
    softened = re.sub(r"\bf\W*u\W*c\W*k\b", "very", softened, flags=re.IGNORECASE)
    softened = re.sub(r"\byou\b", "this situation", softened, flags=re.IGNORECASE)
    softened = re.sub(r"\b[a-z]+ off\b", "I need distance", softened, flags=re.IGNORECASE)
    softened = re.sub(r"\s+", " ", softened).strip(" .!?")
    softened = softened.rstrip(".!?")
    if label == LABEL_SAFE:
        return softened + "."
    lowered_original = cleaned.lower()
    relationship = "generic"
    for key in RELATIONSHIP_PATTERNS:
        if key in lowered_original:
            relationship = key
            break
    base_opener = {
        "gmail": f"Hi {recipient}, I want to phrase this constructively: ",
        "google_docs": f"{recipient}, here is a calmer revision note: ",
    }.get(source_app, f"{recipient}, I want to say this more calmly: ")
    opener = RELATIONSHIP_PATTERNS.get(relationship, {}).get("opener", base_opener)
    if "it hurts me more" in lowered_original:
        softened = "this is affecting me more than I can handle right now, and I need some space before we continue"
    elif (
        "fuck off" in lowered_original
        or "fuckoff" in lowered_original
        or _has_severe_phrase(lowered_original)
        or "leave me alone" in lowered_original
    ):
        softened = "I am too upset to continue this well right now, so I need some space before I respond again"
    elif "you never" in lowered_original or "you always" in lowered_original:
        softened = "I feel unheard when this keeps happening, and I want to explain that without making this worse"
    candidate = (
        f"{opener}{softened}. "
        "I want to come back and explain what I need in a calmer way."
    )
    lowered_candidate = candidate.lower()
    if any(word in lowered_candidate for word in PROFANITY) or any(
        re.search(pattern, lowered_candidate) for pattern in SEVERE_PATTERNS
    ):
        fallback_prefix = {
            "gmail": f"Hi {recipient}, I want to be direct without escalating this: ",
            "google_docs": f"{recipient}, here is a calmer version of this feedback: ",
        }.get(source_app, f"{recipient}, I want to be honest without escalating this: ")
        return (
            f"{fallback_prefix}this situation is affecting me more than I want, "
            "so I need a pause before responding further. "
            "I want to come back with a clearer explanation of what I need."
        )
    return candidate


class CalmSendEngine:
    def __init__(self) -> None:
        self.pipeline, self.metrics = _load_assets()

    def supported_integrations(self) -> list[dict]:
        return SUPPORTED_INTEGRATIONS

    def settings(self) -> dict:
        return load_settings()

    def analyze(
        self,
        message: str,
        recipient: str,
        source_app: str = "generic",
        content_type: str = "chat",
        delay_mode: str = "smart",
    ) -> AnalysisResult:
        word_probabilities = self.pipeline["word_pipeline"].predict_proba([message])[0]
        char_probabilities = self.pipeline["char_pipeline"].predict_proba([message])[0]
        weights = self.pipeline["weights"]
        classes = self.pipeline["classes"]
        blended = (word_probabilities * weights["word"]) + (char_probabilities * weights["char"])
        scored = dict(zip(classes, blended))
        label = str(max(scored, key=scored.get))
        confidence = float(scored[label])
        has_profanity = _contains_profanity(message)
        has_severe = _has_severe_phrase(message)
        if has_severe:
            label = LABEL_HIGH_RISK
            confidence = max(confidence, 0.95)
        elif has_profanity and label == LABEL_SAFE:
            label = LABEL_CAUTION
            confidence = max(confidence, 0.85)
        cooldown_seconds = _cooldown_for(
            message,
            label,
            confidence,
            source_app,
            content_type,
            delay_mode,
        )
        risk_score = _risk_score(message, label, confidence, source_app, content_type)
        return AnalysisResult(
            label=label,
            confidence=confidence,
            cooldown_seconds=cooldown_seconds,
            reasoning=_reasoning_for(message, label, confidence, source_app, content_type, delay_mode),
            rewritten_message=_rewrite_message(message, recipient, label, source_app),
            can_send_now=cooldown_seconds == 0,
            model_accuracy=float(self.metrics["accuracy"]),
            source_app=source_app,
            content_type=content_type,
            delay_mode=delay_mode,
            risk_score=risk_score,
            send_action=_send_action(label, cooldown_seconds),
            blocked_features=_blocked_features(label, cooldown_seconds, delay_mode),
        )
