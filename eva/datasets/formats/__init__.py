"""Base class for dataset format handlers."""
from eva.datasets.manager import DatasetFormat

# Import format handlers to trigger plugin registration
from eva.datasets.formats.json_format import JSONFormat
from eva.datasets.formats.yaml_format import YAMLFormat
from eva.datasets.formats.csv_format import CSVFormat
from eva.datasets.formats.sqlite_format import SQLiteFormat
from eva.datasets.formats.postgres_format import PostgreSQLFormat

__all__ = [
    "DatasetFormat",
    "JSONFormat",
    "YAMLFormat",
    "CSVFormat",
    "SQLiteFormat",
    "PostgreSQLFormat",
]
