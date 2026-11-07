import csv
import hashlib
import io
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

import numpy as np
import pandas as pd


MAX_FILE_SIZE_BYTES = 200 * 1024 * 1024  # 200 MiB upload limit

# Configurable dimension boundaries to protect memory while preserving complete data
DEFAULT_MAX_ROWS: int = int(os.getenv("DATASET_MAX_ROWS", "250000"))
DEFAULT_MAX_COLS: int = int(os.getenv("DATASET_MAX_COLS", "50000"))
DEFAULT_MAX_CELLS: int = int(os.getenv("DATASET_MAX_CELLS", "50000000"))

# Known gene symbol / feature patterns
RE_HGNC = re.compile(r"^[A-Z][A-Z0-9_\-\.]{1,14}$")
RE_ENSEMBL = re.compile(r"^ENS[A-Z]*[GTP]\d+", re.IGNORECASE)
RE_AFFY_PROBE = re.compile(r"^(\d+(_[asx]_at|_at)|ILMN_\d+|probe_\d+)", re.IGNORECASE)
RE_MIRNA = re.compile(r"^(hsa|mmu|rno)-(mir|let)-\w+", re.IGNORECASE)

# Known sample patterns
RE_TCGA = re.compile(r"^TCGA-[A-Z0-9]{2}-[A-Z0-9]{4}", re.IGNORECASE)
RE_GEO_SAMPLE = re.compile(r"^GSM\d+", re.IGNORECASE)
RE_SRA = re.compile(r"^[SED]RR\d+", re.IGNORECASE)
RE_SAMPLE_NAME = re.compile(
    r"^(sample|ctrl|control|tumor|tumour|normal|case|treat|treatment|patient|rep|batch|s|c|t)[\-_#\d]",
    re.IGNORECASE,
)


class DatasetParseError(Exception):
    """Raised when scientific file parsing or validation fails."""
    pass


@dataclass
class OrientationAssessment:
    detected_orientation: str  # "features_as_rows", "samples_as_rows", "ambiguous"
    confidence: float          # 0.0 to 1.0
    reasoning: str
    feature_id_col: str
    sample_id_col: Optional[str]
    feature_evidence: List[str] = field(default_factory=list)
    sample_evidence: List[str] = field(default_factory=list)


@dataclass
class ParsedDataset:
    file_format: str
    content_hash: str
    delimiter: str
    total_raw_rows: int
    total_raw_cols: int
    num_features: int
    num_samples: int
    feature_ids: List[str]
    sample_ids: List[str]
    orientation: OrientationAssessment
    numeric_matrix: pd.DataFrame  # Formatted as features (index) x samples (columns)
    raw_preview_df: pd.DataFrame  # Raw layout for exact table viewing
    metadata_columns: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def compute_sha256(content: bytes) -> str:
    """Compute deterministic SHA-256 hash of file content."""
    hasher = hashlib.sha256()
    hasher.update(content)
    return hasher.hexdigest()


def compute_file_sha256(file_path: Path) -> str:
    """Compute deterministic SHA-256 hash incrementally in 64 KiB chunks."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def detect_encoding(content_bytes: bytes) -> str:
    """Detect text encoding, preferring utf-8 with fallback to latin-1."""
    try:
        content_bytes.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        try:
            content_bytes.decode("latin-1")
            return "latin-1"
        except UnicodeDecodeError:
            raise DatasetParseError(
                "Unable to decode file content. The file must be encoded in UTF-8 or Latin-1 text."
            )


def detect_file_encoding(file_path: Path) -> str:
    """Detect text encoding of a file by inspecting a 64 KiB sample without loading full file."""
    with open(file_path, "rb") as f:
        sample = f.read(65536)
    return detect_encoding(sample)


def sniff_delimiter(sample_text: str, file_ext: str) -> str:
    """Reliably detect delimiter for CSV/TSV/TXT files."""
    if file_ext in [".tsv", ".gct"]:
        return "\t"
    if file_ext == ".csv":
        return ","

    lines = [line for line in sample_text.splitlines() if line.strip()][:20]
    if not lines:
        return ","

    # Count occurrences in top lines
    tab_counts = [l.count("\t") for l in lines]
    comma_counts = [l.count(",") for l in lines]
    semi_counts = [l.count(";") for l in lines]

    avg_tab = sum(tab_counts) / len(tab_counts) if tab_counts else 0
    avg_comma = sum(comma_counts) / len(comma_counts) if comma_counts else 0
    avg_semi = sum(semi_counts) / len(semi_counts) if semi_counts else 0

    if avg_tab > 1 and avg_tab >= avg_comma and avg_tab >= avg_semi:
        return "\t"
    if avg_comma > 1 and avg_comma >= avg_semi:
        return ","
    if avg_semi > 1:
        return ";"

    # Try csv.Sniffer fallback
    try:
        dialect = csv.Sniffer().sniff("\n".join(lines), delimiters=",\t; ")
        return dialect.delimiter
    except Exception:
        return "\t" if (lines and "\t" in lines[0]) else ","


def sniff_delimiter_from_file(file_path: Path, file_ext: str, encoding: str = "utf-8") -> str:
    """Sniff delimiter from file by reading only the first 25 lines."""
    if file_ext in [".tsv", ".gct"]:
        return "\t"
    if file_ext == ".csv":
        return ","

    lines = []
    with open(file_path, "r", encoding=encoding, errors="replace") as f:
        for _ in range(30):
            line = f.readline()
            if not line:
                break
            if line.strip():
                lines.append(line)

    return sniff_delimiter("\n".join(lines), file_ext)


def parse_gct_stream(
    stream,
    content_hash: str,
    max_rows: int = DEFAULT_MAX_ROWS,
    max_cols: int = DEFAULT_MAX_COLS,
    max_cells: int = DEFAULT_MAX_CELLS,
) -> ParsedDataset:
    """
    Parse Gene Cluster Text (GCT) 1.2 or 1.3 scientific formats from an open text stream.
    Validates dimensions, malformed structures, and numeric values with zero unnecessary copies.
    """
    first_line = stream.readline()
    if not first_line or not first_line.strip():
        raise DatasetParseError("The GCT file is empty.")

    version_line = first_line.strip()
    if not (version_line.startswith("#1.2") or version_line.startswith("#1.3")):
        raise DatasetParseError(f"Unrecognized GCT version '{version_line}'. Expected '#1.2' or '#1.3'.")

    is_gct13 = version_line.startswith("#1.3")

    second_line = stream.readline()
    if not second_line:
        raise DatasetParseError("GCT file missing dimensions or header row.")

    dim_parts = second_line.strip().split("\t")
    if len(dim_parts) < 2:
        raise DatasetParseError("Malformed GCT dimensions row. Expected at least row and column counts.")

    try:
        declared_rows = int(dim_parts[0])
        declared_cols = int(dim_parts[1])
        rhd = int(dim_parts[2]) if is_gct13 and len(dim_parts) > 2 else 1
        chd = int(dim_parts[3]) if is_gct13 and len(dim_parts) > 3 else 0
    except ValueError:
        raise DatasetParseError("Invalid numeric values in GCT dimensions header.")

    if declared_rows > max_rows or declared_cols > max_cols or (declared_rows * declared_cols) > max_cells:
        raise DatasetParseError(
            f"GCT declared dimensions ({declared_rows} rows x {declared_cols} columns) exceed configured limits "
            f"(max {max_rows} rows, {max_cols} cols, {max_cells} cells). Never silently truncate data."
        )

    header_line = stream.readline()
    if not header_line:
        raise DatasetParseError("GCT file missing header row.")

    header_cols = header_line.rstrip("\r\n").split("\t")
    num_meta_cols = max(1, rhd if is_gct13 else 1)
    if len(header_cols) <= 1 + num_meta_cols:
        raise DatasetParseError("GCT header does not contain valid sample measurement columns.")

    feature_id_col = header_cols[0] or "Name"
    sample_ids = header_cols[1 + num_meta_cols:]

    # In GCT 1.3, sample metadata rows exist if chd > 0
    if is_gct13 and chd > 0:
        for _ in range(chd):
            meta_line = stream.readline()
            if not meta_line:
                raise DatasetParseError("GCT file truncated before data rows.")

    # Read data rows with high-performance C-parser directly from stream
    try:
        data_df = pd.read_csv(
            stream,
            sep="\t",
            header=None,
            index_col=0,
            low_memory=False,
            encoding_errors="replace",
        )
    except pd.errors.EmptyDataError:
        raise DatasetParseError("GCT file contains header and metadata but no data rows.")
    except Exception as e:
        raise DatasetParseError(f"Failed to extract expression matrix from GCT file: {str(e)}")

    if data_df.empty:
        raise DatasetParseError("GCT file contains header and metadata but no data rows.")

    total_raw_rows = len(data_df) + 3 + (chd if is_gct13 else 0)
    total_raw_cols = len(header_cols)

    if len(data_df) > max_rows or len(sample_ids) > max_cols or (len(data_df) * len(sample_ids)) > max_cells:
        raise DatasetParseError(
            f"GCT parsed dimensions ({len(data_df)} rows x {len(sample_ids)} columns) exceed configured limits "
            f"(max {max_rows} rows, {max_cols} cols, {max_cells} cells). Never silently truncate data."
        )

    feature_ids = [str(x) for x in data_df.index]
    matrix_df = data_df.iloc[:, num_meta_cols:].copy()
    matrix_df.columns = sample_ids
    numeric_df = matrix_df.apply(pd.to_numeric, errors="coerce")

    # Deduplicate index if duplicates exist
    if numeric_df.index.has_duplicates:
        seen: Dict[str, int] = {}
        new_idx = []
        for feat in numeric_df.index:
            f_str = str(feat)
            if f_str in seen:
                seen[f_str] += 1
                new_idx.append(f"{f_str}_{seen[f_str]}")
            else:
                seen[f_str] = 0
                new_idx.append(f_str)
        numeric_df.index = new_idx
        feature_ids = new_idx

    # Raw preview dataframe (first 60 rows)
    raw_preview = data_df.head(60).copy()
    raw_preview.columns = header_cols[1:]
    raw_preview.index.name = feature_id_col

    orientation_assessment = OrientationAssessment(
        detected_orientation="features_as_rows",
        confidence=1.0,
        reasoning=f"Standard GCT {version_line[1:]} format structure: rows are features ({len(feature_ids)}), columns are samples ({len(sample_ids)}).",
        feature_id_col=feature_id_col,
        sample_id_col=None,
        feature_evidence=[f"GCT structure specifies {declared_rows} features."],
        sample_evidence=[f"GCT header defines {len(sample_ids)} sample columns."],
    )

    warnings = []
    if declared_rows != len(feature_ids):
        warnings.append(f"GCT declared {declared_rows} features, but parsed {len(feature_ids)} rows.")
    if declared_cols != len(sample_ids):
        warnings.append(f"GCT declared {declared_cols} samples, but parsed {len(sample_ids)} columns.")

    return ParsedDataset(
        file_format=f"GCT_{version_line[1:]}",
        content_hash=content_hash,
        delimiter="\t",
        total_raw_rows=total_raw_rows,
        total_raw_cols=total_raw_cols,
        num_features=len(feature_ids),
        num_samples=len(sample_ids),
        feature_ids=feature_ids,
        sample_ids=sample_ids,
        orientation=orientation_assessment,
        numeric_matrix=numeric_df,
        raw_preview_df=raw_preview,
        metadata_columns=header_cols[1:1 + num_meta_cols],
        warnings=warnings,
    )


def parse_gct_file(content_text: str, content_hash: str) -> ParsedDataset:
    """Backward compatibility wrapper for in-memory string GCT parsing."""
    return parse_gct_stream(io.StringIO(content_text), content_hash=content_hash)


def score_identifier_list(identifiers: List[str]) -> Tuple[float, float, List[str], List[str]]:
    """
    Score a list of string identifiers against known feature vs sample patterns.
    Returns: (feature_score, sample_score, feature_matches, sample_matches)
    """
    if not identifiers:
        return 0.0, 0.0, [], []

    feature_matches = []
    sample_matches = []

    for item in identifiers[:500]:
        s = str(item).strip()
        if not s:
            continue

        is_feat = False
        is_samp = False

        if RE_ENSEMBL.match(s):
            is_feat = True
            feature_matches.append(f"Ensembl ID: {s}")
        elif RE_AFFY_PROBE.match(s):
            is_feat = True
            feature_matches.append(f"Probe ID: {s}")
        elif RE_MIRNA.match(s):
            is_feat = True
            feature_matches.append(f"miRNA: {s}")
        elif RE_HGNC.match(s) and not RE_SAMPLE_NAME.match(s):
            # Check if likely HGNC symbol
            if any(c.isupper() for c in s) and len(s) >= 2:
                is_feat = True
                if len(feature_matches) < 5:
                    feature_matches.append(f"Gene symbol: {s}")

        if RE_TCGA.match(s):
            is_samp = True
            sample_matches.append(f"TCGA barcode: {s}")
        elif RE_GEO_SAMPLE.match(s):
            is_samp = True
            sample_matches.append(f"GEO sample: {s}")
        elif RE_SRA.match(s):
            is_samp = True
            sample_matches.append(f"SRA run: {s}")
        elif RE_SAMPLE_NAME.match(s):
            is_samp = True
            if len(sample_matches) < 5:
                sample_matches.append(f"Sample name: {s}")

    total = len(identifiers[:500])
    feat_score = len(feature_matches) / total if total > 0 else 0.0
    samp_score = len(sample_matches) / total if total > 0 else 0.0

    return feat_score, samp_score, feature_matches[:5], sample_matches[:5]


def assess_orientation(
    df: pd.DataFrame,
    first_col_name: str,
) -> OrientationAssessment:
    """
    Examine row indices and column names to determine if:
    - features are rows (standard genomics format)
    - samples are rows (standard machine-learning format)
    - ambiguous (uncertain, requires researcher confirmation)
    """
    row_ids = [str(x) for x in df.index]
    col_ids = [str(x) for x in df.columns]

    row_feat_score, row_samp_score, row_feat_ev, row_samp_ev = score_identifier_list(row_ids)
    col_feat_score, col_samp_score, col_feat_ev, col_samp_ev = score_identifier_list(col_ids)

    num_rows = len(df)
    num_cols = len(df.columns)

    # Dimensional heuristics: biological datasets often have 1,000+ genes and < 200 samples
    dim_ratio = num_rows / max(1, num_cols)

    features_as_rows_points = 0.0
    samples_as_rows_points = 0.0

    # Evidence from identifiers
    if row_feat_score > 0.2:
        features_as_rows_points += 4.0 * row_feat_score
    if col_samp_score > 0.1:
        features_as_rows_points += 3.0 * col_samp_score

    if col_feat_score > 0.2:
        samples_as_rows_points += 4.0 * col_feat_score
    if row_samp_score > 0.1:
        samples_as_rows_points += 3.0 * row_samp_score

    # Evidence from dimensions
    if dim_ratio > 3.0:
        features_as_rows_points += 2.0
    elif dim_ratio < 0.33:
        samples_as_rows_points += 2.0

    # First column name signal (e.g. "gene_id", "symbol", "probe")
    first_col_lower = first_col_name.lower()
    if any(k in first_col_lower for k in ["gene", "symbol", "probe", "ensembl", "transcript", "id", "feature"]):
        features_as_rows_points += 1.5
    elif any(k in first_col_lower for k in ["sample", "patient", "case", "barcode", "specimen"]):
        samples_as_rows_points += 1.5

    # Decision logic
    total_points = features_as_rows_points + samples_as_rows_points
    if total_points < 1.0:
        return OrientationAssessment(
            detected_orientation="ambiguous",
            confidence=0.5,
            reasoning="Identifier patterns and dimension ratios do not strongly distinguish genes from samples. Researcher confirmation recommended.",
            feature_id_col=first_col_name,
            sample_id_col=None,
            feature_evidence=[],
            sample_evidence=[],
        )

    if features_as_rows_points >= samples_as_rows_points * 1.5 and features_as_rows_points > 1.5:
        confidence = min(0.98, round(features_as_rows_points / (total_points + 0.1), 2))
        reasoning = (
            f"Detected features as rows based on row identifier patterns ({len(row_feat_ev)} recognized feature patterns) "
            f"and aspect ratio ({num_rows} rows x {num_cols} columns)."
        )
        return OrientationAssessment(
            detected_orientation="features_as_rows",
            confidence=confidence,
            reasoning=reasoning,
            feature_id_col=first_col_name,
            sample_id_col=None,
            feature_evidence=row_feat_ev,
            sample_evidence=col_samp_ev,
        )

    if samples_as_rows_points >= features_as_rows_points * 1.5 and samples_as_rows_points > 1.5:
        confidence = min(0.98, round(samples_as_rows_points / (total_points + 0.1), 2))
        reasoning = (
            f"Detected samples as rows based on column identifier patterns ({len(col_feat_ev)} recognized feature patterns) "
            f"and row identifier patterns ({len(row_samp_ev)} recognized sample patterns)."
        )
        return OrientationAssessment(
            detected_orientation="samples_as_rows",
            confidence=confidence,
            reasoning=reasoning,
            feature_id_col=first_col_name,
            sample_id_col=first_col_name,
            feature_evidence=col_feat_ev,
            sample_evidence=row_samp_ev,
        )

    return OrientationAssessment(
        detected_orientation="ambiguous",
        confidence=0.5,
        reasoning="Both features-as-rows and samples-as-rows have plausible evidence. Please confirm orientation before analysis.",
        feature_id_col=first_col_name,
        sample_id_col=None,
        feature_evidence=row_feat_ev + col_feat_ev,
        sample_evidence=row_samp_ev + col_samp_ev,
    )


def parse_delimited_source(
    source: Union[Path, io.StringIO, io.BytesIO],
    file_ext: str,
    content_hash: str,
    encoding: str = "utf-8",
    max_rows: int = DEFAULT_MAX_ROWS,
    max_cols: int = DEFAULT_MAX_COLS,
    max_cells: int = DEFAULT_MAX_CELLS,
) -> ParsedDataset:
    """Parse CSV, TSV, or TXT matrix file from path or stream with memory bounds."""
    if isinstance(source, Path):
        delimiter = sniff_delimiter_from_file(source, file_ext, encoding=encoding)
        filepath_or_buffer = source
    elif isinstance(source, io.StringIO):
        content_preview = source.getvalue()[:2048]
        delimiter = sniff_delimiter(content_preview, file_ext)
        source.seek(0)
        filepath_or_buffer = source
    else:
        # io.BytesIO
        preview_bytes = source.getvalue()[:2048]
        preview_text = preview_bytes.decode(encoding, errors="replace")
        delimiter = sniff_delimiter(preview_text, file_ext)
        source.seek(0)
        filepath_or_buffer = source

    try:
        raw_df = pd.read_csv(
            filepath_or_buffer,
            sep=delimiter,
            index_col=0,
            low_memory=False,
            encoding=encoding,
            encoding_errors="replace",
        )
    except Exception as e:
        raise DatasetParseError(f"Failed to parse delimited scientific matrix: {str(e)}")

    if raw_df.empty or len(raw_df) == 0 or len(raw_df.columns) == 0:
        raise DatasetParseError("The uploaded scientific matrix contains no data.")

    total_rows = len(raw_df)
    total_cols = len(raw_df.columns) + 1
    total_cells = total_rows * (total_cols - 1)

    if total_rows > max_rows or (total_cols - 1) > max_cols or total_cells > max_cells:
        raise DatasetParseError(
            f"Dataset dimensions ({total_rows} rows x {total_cols - 1} data columns = {total_cells} cells) "
            f"exceed configured maximum limits ({max_rows} rows x {max_cols} cols = {max_cells} cells). "
            "Never silently truncate data to maintain scientific integrity."
        )

    first_col_name = str(raw_df.index.name or "Feature_ID")

    # Assess orientation
    orientation = assess_orientation(raw_df, first_col_name)

    # Standardize orientation
    warnings = []
    if orientation.detected_orientation == "samples_as_rows":
        work_df = raw_df.T
        num_features = len(work_df)
        num_samples = len(work_df.columns)
        feature_ids = [str(x) for x in work_df.index]
        sample_ids = [str(x) for x in work_df.columns]
    else:
        work_df = raw_df
        num_features = len(work_df)
        num_samples = len(work_df.columns)
        feature_ids = [str(x) for x in work_df.index]
        sample_ids = [str(x) for x in work_df.columns]

    # Convert non-numeric cells to NaN only where needed to avoid memory duplication
    numeric_df = work_df.copy(deep=False)
    for col in work_df.columns:
        if not np.issubdtype(work_df[col].dtype, np.number):
            numeric_df[col] = pd.to_numeric(work_df[col], errors="coerce")

    # Deduplicate feature index if needed
    if len(feature_ids) != len(set(feature_ids)):
        dup_count = len(feature_ids) - len(set(feature_ids))
        warnings.append(f"Found {dup_count} duplicate feature identifiers. Indices were disambiguated.")
        seen: Dict[str, int] = {}
        new_index = []
        for feat in feature_ids:
            if feat in seen:
                seen[feat] += 1
                new_index.append(f"{feat}_{seen[feat]}")
            else:
                seen[feat] = 0
                new_index.append(feat)
        numeric_df.index = new_index
        feature_ids = new_index

    if len(sample_ids) != len(set(sample_ids)):
        dup_sample_count = len(sample_ids) - len(set(sample_ids))
        warnings.append(f"Found {dup_sample_count} duplicate sample identifiers.")

    file_format_name = "TSV" if delimiter == "\t" else ("CSV" if delimiter == "," else "TXT")

    return ParsedDataset(
        file_format=file_format_name,
        content_hash=content_hash,
        delimiter=delimiter,
        total_raw_rows=total_rows,
        total_raw_cols=total_cols,
        num_features=num_features,
        num_samples=num_samples,
        feature_ids=feature_ids,
        sample_ids=sample_ids,
        orientation=orientation,
        numeric_matrix=numeric_df,
        raw_preview_df=raw_df.head(60).copy(),
        metadata_columns=[],
        warnings=warnings,
    )


def parse_delimited_file(
    content_text: str,
    file_ext: str,
    content_hash: str,
) -> ParsedDataset:
    """Backward compatibility wrapper for in-memory string delimited parsing."""
    return parse_delimited_source(io.StringIO(content_text), file_ext, content_hash)


def parse_scientific_dataset(
    source: Union[bytes, str, Path],
    original_filename: str,
    content_hash: Optional[str] = None,
    max_rows: Optional[int] = None,
    max_cols: Optional[int] = None,
    max_cells: Optional[int] = None,
) -> ParsedDataset:
    """
    Main entry point for scientific dataset ingestion and orientation assessment.
    Supports both Path/file-based and bytes input with strict security boundaries,
    zero-copy streaming, configurable dimension limits, and encoding detection.
    """
    m_rows = max_rows or DEFAULT_MAX_ROWS
    m_cols = max_cols or DEFAULT_MAX_COLS
    m_cells = max_cells or DEFAULT_MAX_CELLS

    _, ext = os.path.splitext(original_filename.lower())
    clean_ext = ext.strip()

    # Case 1: Path or filesystem string path
    if isinstance(source, Path) or (isinstance(source, str) and os.path.exists(source)):
        file_path = Path(source)
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            raise DatasetParseError("The uploaded file is empty (0 bytes).")
        if file_size > MAX_FILE_SIZE_BYTES:
            raise DatasetParseError(
                f"File size ({file_size / (1024*1024):.1f} MB) exceeds maximum allowed limit of {MAX_FILE_SIZE_BYTES / (1024*1024):.0f} MB."
            )

        resolved_hash = content_hash or compute_file_sha256(file_path)
        encoding = detect_file_encoding(file_path)

        with open(file_path, "r", encoding=encoding, errors="replace") as f_peek:
            first_line = f_peek.readline().strip()

        if clean_ext == ".gct" or first_line.startswith("#1.2") or first_line.startswith("#1.3"):
            with open(file_path, "r", encoding=encoding, errors="replace") as f_gct:
                return parse_gct_stream(
                    f_gct,
                    content_hash=resolved_hash,
                    max_rows=m_rows,
                    max_cols=m_cols,
                    max_cells=m_cells,
                )

        if clean_ext in [".csv", ".tsv", ".txt"] or first_line:
            return parse_delimited_source(
                file_path,
                clean_ext,
                content_hash=resolved_hash,
                encoding=encoding,
                max_rows=m_rows,
                max_cols=m_cols,
                max_cells=m_cells,
            )

        raise DatasetParseError(f"Unsupported file format '{clean_ext}'. Supported formats are CSV, TSV, TXT, and GCT.")

    # Case 2: String content (not an existing path) -> encode to bytes
    if isinstance(source, str):
        source = source.encode("utf-8")

    # Case 3: Raw bytes or bytes-like objects with __len__
    if hasattr(source, "__len__"):
        file_size = len(source)
        if file_size == 0:
            raise DatasetParseError("The uploaded file is empty (0 bytes).")
        if file_size > MAX_FILE_SIZE_BYTES:
            raise DatasetParseError(
                f"File size ({file_size / (1024*1024):.1f} MB) exceeds maximum allowed limit of {MAX_FILE_SIZE_BYTES / (1024*1024):.0f} MB."
            )

        if not isinstance(source, (bytes, bytearray)):
            raise DatasetParseError(f"Unsupported source type for dataset parser: {type(source)}")

        resolved_hash = content_hash or compute_sha256(source)
        encoding = detect_encoding(source)

        sample_prefix = source[:512].decode(encoding, errors="replace").strip()
        first_line = sample_prefix.split("\n")[0].strip() if sample_prefix else ""

        if clean_ext == ".gct" or first_line.startswith("#1.2") or first_line.startswith("#1.3"):
            text_stream = io.StringIO(source.decode(encoding, errors="replace"))
            return parse_gct_stream(
                text_stream,
                content_hash=resolved_hash,
                max_rows=m_rows,
                max_cols=m_cols,
                max_cells=m_cells,
            )

        if clean_ext in [".csv", ".tsv", ".txt"] or first_line:
            byte_stream = io.BytesIO(source)
            return parse_delimited_source(
                byte_stream,
                clean_ext,
                content_hash=resolved_hash,
                encoding=encoding,
                max_rows=m_rows,
                max_cols=m_cols,
                max_cells=m_cells,
            )

        raise DatasetParseError(f"Unsupported file format '{clean_ext}'. Supported formats are CSV, TSV, TXT, and GCT.")

    raise DatasetParseError(f"Unsupported source type for dataset parser: {type(source)}")

