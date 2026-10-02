from dataclasses import dataclass

from extractor import normalize_text
from models import Job


POSITIVE_SPONSORSHIP = (
    "visa sponsorship",
    "sponsorship available",
    "will sponsor",
    "can sponsor",
    "work permit sponsorship",
    "employment sponsorship",
)

POSITIVE_RELOCATION = (
    "relocation assistance",
    "relocation support",
    "relocation package",
    "relocation provided",
    "international relocation",
)

GLOBAL_REMOTE = (
    "remote worldwide",
    "work from anywhere",
    "global remote",
    "remote globally",
    "worldwide remote",
)

NEGATIVE_SPONSORSHIP = (
    "no visa sponsorship",
    "unable to sponsor",
    "cannot sponsor",
    "will not sponsor",
    "without sponsorship",
    "must be authorized to work",
)


@dataclass(frozen=True)
class InternationalSignals:
    sponsorship_positive: bool = False
    relocation_positive: bool = False
    global_remote_positive: bool = False
    sponsorship_negative: bool = False

    @property
    def has_positive_overseas_signal(self) -> bool:
        return (
            self.sponsorship_positive
            or self.relocation_positive
            or self.global_remote_positive
        )


def detect_international_signals(job: Job) -> InternationalSignals:
    text = normalize_text(f"{job.title} {job.location} {job.description}")
    return InternationalSignals(
        sponsorship_positive=any(x in text for x in POSITIVE_SPONSORSHIP),
        relocation_positive=any(x in text for x in POSITIVE_RELOCATION),
        global_remote_positive=any(x in text for x in GLOBAL_REMOTE),
        sponsorship_negative=any(x in text for x in NEGATIVE_SPONSORSHIP),
    )


def classify_search_track(job: Job) -> str:
    text = normalize_text(f"{job.location} {job.description}")
    if "india" in text:
        return "india"

    signals = detect_international_signals(job)
    if signals.global_remote_positive:
        return "global_remote"
    if signals.sponsorship_positive or signals.relocation_positive:
        return "global_relocation"
    return "international_unverified"
