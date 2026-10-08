"""Deterministic analysis of common SQL schema migration changes."""

import re
from collections.abc import Iterable
from enum import Enum
from pathlib import PurePath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

IDENTIFIER = r'(?:"(?:""|[^"])+"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][\w$]*)'
QUALIFIED_NAME = rf"{IDENTIFIER}(?:\s*\.\s*{IDENTIFIER})?"
SUPPORTED_SOURCE_SUFFIXES = {
    ".java",
    ".kt",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".vue",
    ".html",
}
MAX_SOURCE_TOTAL_BYTES = 10 * 1024 * 1024
MAX_SOURCE_FILE_BYTES = 2 * 1024 * 1024


class MigrationSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class MigrationFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str
    table: str | None = None
    column: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    line: int = Field(ge=1)
    statement: str
    breaking: bool
    risk_points: int = Field(ge=0, le=100)
    reason: str
    recommendation: str


class CodeReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    categories: list[str]
    line: int = Field(ge=1)
    identifiers: list[str]


class RiskBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_risk: int = Field(ge=0, le=35)
    dependency_risk: int = Field(ge=0, le=30)
    api_risk: int = Field(ge=0, le=20)
    data_loss_risk: int = Field(ge=0, le=15)


class UnsupportedStatement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line: int = Field(ge=1)
    statement: str
    reason: str


class MigrationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_score: int = Field(ge=0, le=100)
    severity: MigrationSeverity
    breaking: bool
    human_review_required: bool
    breakdown: RiskBreakdown
    findings: list[MigrationFinding]
    references: list[CodeReference]
    unsupported_statements: list[UnsupportedStatement]
    recommendations: list[str]


class _Statement:
    def __init__(self, text: str, line: int) -> None:
        self.text = text.strip()
        self.line = line


_RULES: dict[str, dict[str, Any]] = {
    "table_dropped": {
        "points": 35,
        "breaking": True,
        "data_loss": 15,
        "reason": "Dropping a table removes its structure and stored rows.",
        "recommendation": "Check backups and all consumers; use a staged archival/removal plan.",
    },
    "column_dropped": {
        "points": 28,
        "breaking": True,
        "data_loss": 13,
        "reason": "Dropping a column permanently removes its stored values.",
        "recommendation": "Use an expand-contract rollout; remove the column only after consumers stop using it.",
    },
    "column_renamed": {
        "points": 25,
        "breaking": True,
        "data_loss": 0,
        "reason": "Existing queries and application mappings may still use the old column name.",
        "recommendation": "Add the new column, dual-write/backfill, migrate readers, then remove the old column in a later release.",
    },
    "table_renamed": {
        "points": 30,
        "breaking": True,
        "data_loss": 0,
        "reason": "Existing queries, mappings, and foreign keys may still refer to the old table name.",
        "recommendation": "Prefer a staged compatibility view or a coordinated expand-contract rollout.",
    },
    "column_type_changed": {
        "points": 24,
        "breaking": True,
        "data_loss": 8,
        "reason": "A type change can reject, truncate, or reinterpret existing data and caller values.",
        "recommendation": "Validate existing values and use a compatible shadow-column migration with an explicit backfill.",
    },
    "not_null_added": {
        "points": 20,
        "breaking": True,
        "data_loss": 5,
        "reason": "Existing null rows or writers that omit this column can make the migration or future writes fail.",
        "recommendation": "Backfill null rows and deploy writers that provide a value before enforcing NOT NULL.",
    },
    "not_null_removed": {
        "points": 2,
        "breaking": False,
        "data_loss": 0,
        "reason": "The database will accept NULL values that it previously rejected.",
        "recommendation": "Confirm downstream code and consumers handle null values.",
    },
    "unique_added": {
        "points": 12,
        "breaking": True,
        "data_loss": 0,
        "reason": "Existing duplicate values can prevent the constraint from being created; future duplicate writes will fail.",
        "recommendation": "Find and resolve duplicates before adding the unique constraint.",
    },
    "foreign_key_dropped": {
        "points": 20,
        "breaking": True,
        "data_loss": 0,
        "reason": "Removing a foreign key stops the database from enforcing this relationship.",
        "recommendation": "Confirm application-level integrity checks replace the constraint before removal.",
    },
    "constraint_dropped": {
        "points": 12,
        "breaking": True,
        "data_loss": 0,
        "reason": "Removing a constraint may disable a database-enforced invariant.",
        "recommendation": "Identify the constraint type and verify an equivalent invariant remains enforced.",
    },
    "index_dropped": {
        "points": 8,
        "breaking": False,
        "data_loss": 0,
        "reason": "Removing an index can turn previously efficient queries into table scans.",
        "recommendation": "Check query plans and production usage before removing the index.",
    },
    "column_added": {
        "points": 2,
        "breaking": False,
        "data_loss": 0,
        "reason": "Adding a column is usually compatible, but defaults and nullability affect existing rows and writers.",
        "recommendation": "Prefer a nullable column or a safe constant default, then backfill separately if needed.",
    },
    "foreign_key_added": {
        "points": 4,
        "breaking": False,
        "data_loss": 0,
        "reason": "Adding a foreign key can fail if existing rows contain orphaned references.",
        "recommendation": "Audit and repair orphaned rows before enforcing the relationship.",
    },
    "table_created": {
        "points": 2,
        "breaking": False,
        "data_loss": 0,
        "reason": "A new table is additive, but its constraints and rollout still need validation.",
        "recommendation": "Review constraints and deploy consumers only after the table is available.",
    },
}


def analyze_migration(
    sql: str,
    source_files: Iterable[tuple[str, str]] = (),
) -> MigrationReport:
    """Analyze a migration script and optional source files for likely blast radius."""
    statements = _split_statements(sql)
    findings: list[MigrationFinding] = []
    unsupported: list[UnsupportedStatement] = []

    for statement in statements:
        parsed, unsupported_actions = _parse_statement(statement)
        if parsed:
            findings.extend(parsed)
        for action in unsupported_actions:
            unsupported.append(
                UnsupportedStatement(
                    line=statement.line,
                    statement=action,
                    reason=(
                        "This ALTER TABLE action is not currently recognized; "
                        "review it manually."
                    ),
                )
            )
        if parsed or unsupported_actions:
            continue
        if statement.text and _is_schema_statement(statement.text):
            unsupported.append(
                UnsupportedStatement(
                    line=statement.line,
                    statement=statement.text,
                    reason="This DDL form is not currently recognized; review it manually.",
                )
            )
        elif statement.text and _is_unmodeled_data_change(statement.text):
            unsupported.append(
                UnsupportedStatement(
                    line=statement.line,
                    statement=statement.text,
                    reason="Data-changing SQL is not modeled; inspect row-level effects manually.",
                )
            )

    references: list[CodeReference] = []
    seen_references: set[tuple[str, str, int, tuple[str, ...]]] = set()
    unique_source_files = list(source_files)
    total_source_bytes = sum(len(text.encode("utf-8")) for _, text in unique_source_files)
    if total_source_bytes > MAX_SOURCE_TOTAL_BYTES:
        raise ValueError(
            f"Source files exceed the {MAX_SOURCE_TOTAL_BYTES // (1024 * 1024)} MiB total limit."
        )
    for name, content in unique_source_files:
        if len(content.encode("utf-8")) > MAX_SOURCE_FILE_BYTES:
            raise ValueError(
                f"Source file '{name}' exceeds the "
                f"{MAX_SOURCE_FILE_BYTES // (1024 * 1024)} MiB per-file limit."
            )
        for finding in findings:
            reference = _find_reference(name, content, finding)
            if reference is None:
                continue
            key = (
                finding.operation,
                reference.file,
                reference.line,
                tuple(reference.identifiers),
            )
            if key not in seen_references:
                seen_references.add(key)
                references.append(reference)

    references.sort(key=lambda reference: (reference.file.lower(), reference.line))
    schema_risk = min(35, sum(finding.risk_points for finding in findings))
    data_loss_risk = min(
        15,
        sum(_RULES[finding.operation]["data_loss"] for finding in findings),
    )
    dependency_risk = min(30, 5 * len(references))
    api_references = sum("API" in reference.categories for reference in references)
    api_risk = min(20, 5 * api_references)
    total_risk = min(
        100,
        schema_risk + dependency_risk + api_risk + data_loss_risk,
    )

    severity = _severity_for(total_risk)
    recommendations = list(dict.fromkeys(finding.recommendation for finding in findings))
    if unsupported:
        recommendations.append(
            "Review every unsupported statement manually; the score covers recognized DDL only."
        )
    if references:
        recommendations.append(
            "Migrate the listed application references before removing or changing the old schema contract."
        )
    if not findings:
        recommendations.append(
            "No supported schema changes were recognized; review unsupported statements before treating this migration as safe."
        )

    return MigrationReport(
        risk_score=total_risk,
        severity=severity,
        breaking=any(finding.breaking for finding in findings),
        human_review_required=bool(unsupported) or bool(findings),
        breakdown=RiskBreakdown(
            schema_risk=schema_risk,
            dependency_risk=dependency_risk,
            api_risk=api_risk,
            data_loss_risk=data_loss_risk,
        ),
        findings=findings,
        references=references,
        unsupported_statements=unsupported,
        recommendations=recommendations,
    )


def _split_statements(sql: str) -> list[_Statement]:
    statements: list[_Statement] = []
    buffer: list[str] = []
    line = 1
    statement_line = 1
    index = 0
    quote: str | None = None
    block_comment_depth = 0
    line_comment = False
    dollar_quote: str | None = None
    has_content = False

    while index < len(sql):
        char = sql[index]
        next_char = sql[index + 1] if index + 1 < len(sql) else ""

        if line_comment:
            if char == "\n":
                line_comment = False
                buffer.append("\n")
                line += 1
                if not has_content:
                    statement_line = line
            index += 1
            continue
        if block_comment_depth:
            if char == "/" and next_char == "*":
                block_comment_depth += 1
                index += 2
                continue
            if char == "*" and next_char == "/":
                block_comment_depth -= 1
                index += 2
                continue
            if char == "\n":
                buffer.append("\n")
                line += 1
                if not has_content:
                    statement_line = line
            index += 1
            continue
        if dollar_quote is not None:
            if sql.startswith(dollar_quote, index):
                buffer.extend(dollar_quote)
                index += len(dollar_quote)
                dollar_quote = None
                continue
            buffer.append(char)
            if char == "\n":
                line += 1
            index += 1
            continue
        if quote is not None:
            buffer.append(char)
            if char == quote:
                if next_char == quote:
                    buffer.append(next_char)
                    index += 2
                    continue
                quote = None
            elif char == "\\" and next_char:
                buffer.append(next_char)
                if next_char == "\n":
                    line += 1
                index += 2
                continue
            if char == "\n":
                line += 1
            index += 1
            continue

        if char == "-" and next_char == "-":
            line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            block_comment_depth = 1
            index += 2
            continue
        if char in {"'", '"', "`"}:
            if not has_content:
                statement_line = line
            quote = char
            buffer.append(char)
            has_content = True
            index += 1
            continue
        if char == "[":
            if not has_content:
                statement_line = line
            quote = "]"
            buffer.append(char)
            has_content = True
            index += 1
            continue
        if char == "$":
            match = re.match(r"\$(?:[A-Za-z_][\w]*)?\$", sql[index:])
            if match:
                if not has_content:
                    statement_line = line
                dollar_quote = match.group(0)
                buffer.extend(dollar_quote)
                has_content = True
                index += len(dollar_quote)
                continue
        if char == ";":
            statements.append(_Statement("".join(buffer), statement_line))
            buffer.clear()
            has_content = False
            index += 1
            statement_line = line
            continue
        if not char.isspace() and not has_content:
            statement_line = line
            has_content = True
        buffer.append(char)
        if char == "\n":
            line += 1
        index += 1

    if "".join(buffer).strip():
        statements.append(_Statement("".join(buffer), statement_line))
    return [statement for statement in statements if statement.text]


def _parse_statement(
    statement: _Statement,
) -> tuple[list[MigrationFinding], list[str]]:
    text = statement.text.strip()

    drop_table = re.match(
        rf"^DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?P<table>{QUALIFIED_NAME})",
        text,
        re.IGNORECASE,
    )
    if drop_table:
        return [
            _finding(
                "table_dropped",
                statement,
                table=drop_table.group("table"),
            )
        ], []

    drop_index = re.match(
        rf"^DROP\s+(?:INDEX|KEY)\s+(?:IF\s+EXISTS\s+)?(?P<index>{IDENTIFIER})",
        text,
        re.IGNORECASE,
    )
    if drop_index:
        return [
            _finding(
                "index_dropped",
                statement,
                column=_unquote_identifier(drop_index.group("index")),
            )
        ], []

    match = re.match(
        rf"^(?:MODIFY\s+(?:COLUMN\s+)?(?P<column>{IDENTIFIER})\s+|"
        rf"ALTER\s+COLUMN\s+(?P<alter_column>{IDENTIFIER})\s+SET\s+DATA\s+TYPE\s+)"
        r"(?P<type>[A-Za-z][\w]*(?:\s*\([^)]*\))?)",
        text,
        re.IGNORECASE,
    )
    if match:
        column_name = match["column"] or match["alter_column"]
        findings = [
            _finding(
                "column_type_changed",
                statement,
                None,
                _unquote_identifier(column_name),
                None,
                _first_type_token(match["type"]),
            )
        ]
        if re.search(r"\bNOT\s+NULL\b", text, re.IGNORECASE):
            findings.append(
                _finding(
                    "not_null_added",
                    statement,
                    None,
                    _unquote_identifier(column_name),
                )
            )
        return findings, []

    create_table = re.match(
        rf"^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<table>{QUALIFIED_NAME})",
        text,
        re.IGNORECASE,
    )
    if create_table:
        return [
            _finding(
                "table_created",
                statement,
                table=create_table.group("table"),
            )
        ], []

    alter_table = re.match(
        rf"^ALTER\s+TABLE\s+(?:ONLY\s+)?(?P<table>{QUALIFIED_NAME})\s+(?P<actions>.+)$",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if not alter_table:
        return [], []

    table = _unquote_qualified(alter_table.group("table"))
    findings: list[MigrationFinding] = []
    unsupported_actions: list[str] = []
    actions = _split_top_level_actions(alter_table.group("actions"))
    for action in actions:
        parsed = _parse_alter_action(action, table, statement)
        if parsed:
            findings.extend(parsed)
        else:
            unsupported_actions.append(
                f"ALTER TABLE {table} {action}"
            )
    return findings, unsupported_actions


def _parse_alter_action(
    action: str, table: str, statement: _Statement
) -> list[MigrationFinding]:
    action = action.strip().rstrip(",")
    match = re.match(rf"^RENAME\s+TO\s+(?P<table>{QUALIFIED_NAME})", action, re.I)
    if match:
        return [
            _finding(
                "table_renamed",
                statement,
                table,
                old_value=table,
                new_value=_unquote_qualified(match["table"]),
            )
        ]
    match = re.match(
        rf"^DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?(?P<column>{IDENTIFIER})",
        action,
        re.IGNORECASE,
    )
    if match:
        return [_finding("column_dropped", statement, table, _unquote_identifier(match["column"]))]

    match = re.match(
        rf"^DROP\s+(?:INDEX|KEY)\s+(?:IF\s+EXISTS\s+)?(?P<index>{IDENTIFIER})",
        action,
        re.IGNORECASE,
    )
    if match:
        return [
            _finding(
                "index_dropped",
                statement,
                table,
                _unquote_identifier(match["index"]),
            )
        ]

    match = re.match(
        rf"^RENAME\s+COLUMN\s+(?P<old>{IDENTIFIER})\s+TO\s+(?P<new>{IDENTIFIER})",
        action,
        re.IGNORECASE,
    )
    if match:
        return [
            _finding(
                "column_renamed",
                statement,
                table,
                _unquote_identifier(match["old"]),
                _unquote_identifier(match["old"]),
                _unquote_identifier(match["new"]),
            )
        ]

    match = re.match(
        rf"^CHANGE\s+(?:COLUMN\s+)?(?P<old>{IDENTIFIER})\s+(?P<new>{IDENTIFIER})\s+(?P<type>.+)$",
        action,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        old_name = _unquote_identifier(match["old"])
        new_name = _unquote_identifier(match["new"])
        if old_name.lower() != new_name.lower():
            return [
                _finding(
                    "column_renamed",
                    statement,
                    table,
                    old_name,
                    old_name,
                    new_name,
                ),
                _finding(
                    "column_type_changed",
                    statement,
                    table,
                    new_name,
                    old_name,
                    _first_type_token(match["type"]),
                ),
            ]
        return [
            _finding(
                "column_type_changed",
                statement,
                table,
                old_name,
                None,
                _first_type_token(match["type"]),
            )
        ]

    match = re.match(
        rf"^ALTER\s+COLUMN\s+(?P<column>{IDENTIFIER})\s+(?:SET\s+DATA\s+TYPE|TYPE)\s+(?P<type>.+)$",
        action,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return [
            _finding(
                "column_type_changed",
                statement,
                table,
                _unquote_identifier(match["column"]),
                None,
                _first_type_token(match["type"]),
            )
        ]

    match = re.match(
        rf"^(?:MODIFY\s+(?:COLUMN\s+)?(?P<column>{IDENTIFIER})\s+|"
        rf"ALTER\s+COLUMN\s+(?P<alter_column>{IDENTIFIER})\s+SET\s+DATA\s+TYPE\s+)"
        r"(?P<type>.+)$",
        action,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        column_name = match["column"] or match["alter_column"]
        return [
            _finding(
                "column_type_changed",
                statement,
                table,
                _unquote_identifier(column_name),
                None,
                _first_type_token(match["type"]),
            )
        ]

    match = re.match(
        rf"^ALTER\s+COLUMN\s+(?P<column>{IDENTIFIER})\s+SET\s+NOT\s+NULL\b",
        action,
        re.IGNORECASE,
    )
    if match:
        return [
            _finding(
                "not_null_added",
                statement,
                table,
                _unquote_identifier(match["column"]),
            )
        ]

    match = re.match(
        rf"^ALTER\s+COLUMN\s+(?P<column>{IDENTIFIER})\s+DROP\s+NOT\s+NULL\b",
        action,
        re.IGNORECASE,
    )
    if match:
        return [
            _finding(
                "not_null_removed",
                statement,
                table,
                _unquote_identifier(match["column"]),
            )
        ]

    match = re.match(
        rf"^ADD\s+(?:CONSTRAINT\s+(?P<constraint>{IDENTIFIER})\s+)?"
        r"(?:UNIQUE|UNIQUE\s+(?:KEY|INDEX))\b",
        action,
        re.IGNORECASE,
    )
    if match:
        return [
            _finding(
                "unique_added",
                statement,
                table,
                _unquote_identifier(match["constraint"])
                if match["constraint"]
                else None,
            )
        ]

    match = re.match(
        rf"^ADD\s+(?:CONSTRAINT\s+(?P<constraint>{IDENTIFIER})\s+)?FOREIGN\s+KEY\b",
        action,
        re.IGNORECASE,
    )
    if match:
        return [
            _finding(
                "foreign_key_added",
                statement,
                table,
                _unquote_identifier(match["constraint"])
                if match["constraint"]
                else None,
            )
        ]

    match = re.match(
        rf"^DROP\s+FOREIGN\s+KEY\s+(?P<constraint>{IDENTIFIER})",
        action,
        re.IGNORECASE,
    )
    if match:
        return [
            _finding(
                "foreign_key_dropped",
                statement,
                table,
                _unquote_identifier(match["constraint"]),
            )
        ]

    match = re.match(
        rf"^DROP\s+CONSTRAINT\s+(?:IF\s+EXISTS\s+)?(?P<constraint>{IDENTIFIER})",
        action,
        re.IGNORECASE,
    )
    if match:
        constraint = _unquote_identifier(match["constraint"])
        operation = (
            "foreign_key_dropped"
            if "fk" in constraint.lower() or "foreign" in constraint.lower()
            else "constraint_dropped"
        )
        return [_finding(operation, statement, table, constraint)]

    match = re.match(
        rf"^ADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?"
        rf"(?P<column>{IDENTIFIER})\s+(?P<definition>.+)$",
        action,
        re.IGNORECASE | re.DOTALL,
    )
    if match and not re.match(r"^(?:CONSTRAINT|PRIMARY|FOREIGN|UNIQUE|CHECK)\b", action, re.I):
        definition = match["definition"].strip()
        if re.match(r"^(?:UNIQUE|REFERENCES)\b", definition, re.IGNORECASE):
            operation = (
                "unique_added"
                if definition.upper().startswith("UNIQUE")
                else "foreign_key_added"
            )
        else:
            operation = "column_added"
        findings = [
            _finding(
                operation,
                statement,
                table,
                _unquote_identifier(match["column"]),
                None,
                _first_type_token(definition),
            )
        ]
        if (
            operation == "column_added"
            and re.search(r"\bNOT\s+NULL\b", definition, re.IGNORECASE)
        ):
            findings.append(
                _finding(
                    "not_null_added",
                    statement,
                    table,
                    _unquote_identifier(match["column"]),
                )
            )
        return findings
    return []


def _finding(
    operation: str,
    statement: _Statement,
    table: str | None = None,
    column: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
) -> MigrationFinding:
    rule = _RULES[operation]
    return MigrationFinding(
        operation=operation,
        table=_unquote_qualified(table) if table else None,
        column=column,
        old_value=old_value,
        new_value=new_value,
        line=statement.line,
        statement=statement.text,
        breaking=rule["breaking"],
        risk_points=rule["points"],
        reason=rule["reason"],
        recommendation=rule["recommendation"],
    )


def _find_reference(
    filename: str,
    source: str,
    finding: MigrationFinding,
) -> CodeReference | None:
    names = [name for name in (finding.table, finding.column) if name]
    if not names:
        return None
    escaped = [re.escape(name) for name in names]
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_$])(?:{'|'.join(escaped)})(?![A-Za-z0-9_$])",
        re.IGNORECASE,
    )
    for line_number, line in enumerate(source.splitlines(), start=1):
        matches = list(pattern.finditer(line))
        if not matches:
            continue
        categories = _source_categories(filename, source)
        return CodeReference(
            file=filename,
            categories=categories,
            line=line_number,
            identifiers=list(
                dict.fromkeys(
                    match.group(0).strip('"`[]') for match in matches
                )
            ),
        )
    return None


def _source_categories(filename: str, source: str) -> list[str]:
    file_path = PurePath(filename)
    name = filename.lower()
    categories: list[str] = []
    if any(token in name for token in ("entity", "model", "schema")) or re.search(
        r"@Entity\b|@Table\s*\(", source, re.IGNORECASE
    ):
        categories.append("ENTITY")
    if any(token in name for token in ("repository", "repo", "dao", "query")):
        categories.append("REPOSITORY")
    if any(token in name for token in ("controller", "router", "endpoint", "route")) or re.search(
        r"@(?:Get|Post|Put|Delete|Patch)Mapping\b|@RequestMapping\b",
        source,
        re.IGNORECASE,
    ):
        categories.append("API")
    if any(token in name for token in ("dto", "request", "response", "payload")):
        categories.append("DTO")
    if file_path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx", ".vue", ".html"}:
        categories.append("FRONTEND")
    return categories or ["SOURCE"]


def _split_top_level_actions(actions: str) -> list[str]:
    result: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    index = 0
    while index < len(actions):
        char = actions[index]
        next_char = actions[index + 1] if index + 1 < len(actions) else ""
        if quote:
            current.append(char)
            if char == quote:
                if next_char == quote:
                    current.append(next_char)
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if char in {"'", '"', "`"}:
            quote = char
            current.append(char)
        elif char == "[":
            quote = "]"
            current.append(char)
        elif char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth = max(0, depth - 1)
            current.append(char)
        elif char == "," and depth == 0:
            result.append("".join(current).strip())
            current.clear()
        else:
            current.append(char)
        index += 1
    if current:
        result.append("".join(current).strip())
    return [action for action in result if action]


def _is_schema_statement(statement: str) -> bool:
    return bool(
        re.match(
            r"^\s*(?:ALTER|CREATE|DROP|RENAME|TRUNCATE)\b",
            statement,
            re.IGNORECASE,
        )
    )


def _is_unmodeled_data_change(statement: str) -> bool:
    return bool(
        re.match(r"^\s*(?:UPDATE|DELETE|INSERT|MERGE)\b", statement, re.IGNORECASE)
    )


def _unquote_identifier(identifier: str) -> str:
    identifier = identifier.strip()
    if len(identifier) >= 2 and (
        (identifier[0] == '"' and identifier[-1] == '"')
        or (identifier[0] == "`" and identifier[-1] == "`")
        or (identifier[0] == "[" and identifier[-1] == "]")
    ):
        return identifier[1:-1].replace('""', '"')
    return identifier


def _unquote_qualified(name: str) -> str:
    parts = _split_qualified_name(name)
    return ".".join(_unquote_identifier(part) for part in parts)


def _qualified_parent(name: str) -> str | None:
    parts = _split_qualified_name(name)
    return ".".join(_unquote_identifier(part) for part in parts[:-1]) or None


def _split_qualified_name(name: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s*\.\s*", name.strip())]


def _first_type_token(definition: str) -> str | None:
    match = re.match(r"([A-Za-z][\w]*(?:\s*\([^)]*\))?)", definition.strip())
    return re.sub(r"\s+", "", match.group(1)) if match else None


def _severity_for(risk_score: int) -> MigrationSeverity:
    if risk_score >= 80:
        return MigrationSeverity.CRITICAL
    if risk_score >= 50:
        return MigrationSeverity.HIGH
    if risk_score >= 20:
        return MigrationSeverity.MEDIUM
    return MigrationSeverity.LOW
