"""台本品質チェックのドメインモデル。"""

from dataclasses import dataclass
from enum import StrEnum


class QualitySeverity(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class QualityIssue:
    rule: str
    message: str
    severity: QualitySeverity


@dataclass(frozen=True, slots=True)
class QualityReport:
    character_count: int
    estimated_duration_seconds: float
    issues: tuple[QualityIssue, ...]

    @property
    def is_acceptable(self) -> bool:
        return not any(issue.severity is QualitySeverity.ERROR for issue in self.issues)


@dataclass(frozen=True, slots=True)
class QualityCheckResult:
    """品質ルール1件の判定結果。"""

    check_name: str
    severity: QualitySeverity
    message: str
    value: str | int | float | None = None


@dataclass(frozen=True, slots=True)
class ProjectQualityReport:
    """動画プロジェクト全体の品質判定結果。"""

    project_dir: str
    checks: tuple[QualityCheckResult, ...]
    improvements: tuple[str, ...] = ()

    @property
    def has_errors(self) -> bool:
        return any(check.severity is QualitySeverity.ERROR for check in self.checks)
