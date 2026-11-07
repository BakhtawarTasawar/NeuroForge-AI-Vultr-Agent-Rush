import csv
import hashlib
import io
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd


MAX_FILE_SIZE_BYTES = 200 * 1024 * 1024  # 200 MiB upload limit

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

    avg_tab = sum(tab_counts) / len(tab_counts)
    avg_comma = sum(comma_counts) / len(comma_counts)
    avg_semi = sum(semi_counts) / len(semi_counts)

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
        return "\t" if "\t" in lines[0] else ","


def parse_gct_file(content_text: str, content_hash: str) -> ParsedDataset:
    """
    Parse Gene Cluster Text (GCT) 1.2 or 1.3 scientific formats.
    GCT 1.2 format:
      Line 1: #1.2
      Line 2: <#rows>\t<#cols>
      Line 3: Name\tDescription\t<sample1>\t<sample2>...
      Line 4+: <gene1>\t<desc1>\t<val1>\t<val2>...

    GCT 1.3 format:
      Line 1: #1.3
      Line 2: <#rows>\t<#cols>\t<#rhd>\t<#chd>
      Line 3: id\tdescription...\t<sample1>...
      [optional column metadata rows]
      Line 4+: row metadata + data
    """
    lines = content_text.splitlines()
    if not lines:
        raise DatasetParseError("The GCT file is empty.")

    version_line = lines[0].strip()
    if not (version_line.startswith("#1.2") or version_line.startswith("#1.3")):
        raise DatasetParseError(f"Unrecognized GCT version '{version_line}'. Expected '#1.2' or '#1.3'.")

    is_gct13 = version_line.startswith("#1.3")

    if len(lines) < 3:
        raise DatasetParseError("GCT file missing dimensions or header row.")

    dim_parts = lines[1].strip().split("\t")
    if len(dim_parts) < 2:
        raise DatasetParseError("Malformed GCT dimensions row. Expected at least row and column counts.")

    try:
        declared_rows = int(dim_parts[0])
        declared_cols = int(dim_parts[1])
        rhd = int(dim_parts[2]) if is_gct13 and len(dim_parts) > 2 else 1
        chd = int(dim_parts[3]) if is_gct13 and len(dim_parts) > 3 else 0
    except ValueError:
        raise DatasetParseError("Invalid numeric values in GCT dimensions header.")

    # Header is at index 2
    header_line_idx = 2
    header_cols = lines[header_line_idx].split("\t")
    
    # In GCT 1.3, sample metadata rows exist if chd > 0
    data_start_idx = header_line_idx + 1 + chd
    if data_start_idx >= len(lines):
        raise DatasetParseError("GCT file contains header and metadata but no data rows.")

    data_lines = [l for l in lines[data_start_idx:] if l.strip()]
    
    # Read into DataFrame
    # Column 0: feature ID ("Name" or "id")
    # Columns 1 to 1+rhd: feature metadata (e.g. "Description")
    # Columns 1+rhd to end: sample measurements
    num_meta_cols = max(1, rhd if is_gct13 else 1)
    
    feature_id_col = header_cols[0] or "Name"
    sample_ids = header_cols[1 + num_meta_cols:]
    
    matrix_records = []
    feature_ids = []
    
    for line in data_lines:
        parts = line.split("\t")
        if len(parts) <= 1:
            continue
        feat_id = parts[0].strip()
        feature_ids.append(feat_id)
        numeric_vals = []
        for val_str in parts[1 + num_meta_cols:]:
            try:
                numeric_vals.append(float(val_str.strip()) if val_str.strip() != "" else np.nan)
            except ValueError:
                numeric_vals.append(np.nan)
        matrix_records.append(numeric_vals)

    if not matrix_records or not sample_ids:
        raise DatasetParseError("Failed to extract expression matrix from GCT file.")

    matrix_df = pd.DataFrame(matrix_records, index=feature_ids, columns=sample_ids)
    
    # Deduplicate index if duplicates exist
    if matrix_df.index.has_duplicates:
        matrix_df.index = [f"{idx}_{i}" if count > 1 else idx 
                           for i, (idx, count) in enumerate(zip(matrix_df.index, pd.Series(matrix_df.index).map(pd.Series(matrix_df.index).value_counts())))]

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
        total_raw_rows=len(lines),
        total_raw_cols=len(header_cols),
        num_features=len(feature_ids),
        num_samples=len(sample_ids),
        feature_ids=list(matrix_df.index),
        sample_ids=list(matrix_df.columns),
        orientation=orientation_assessment,
        numeric_matrix=matrix_df,
        raw_preview_df=pd.read_csv(io.StringIO("\n".join(lines[header_line_idx:header_line_idx + 60])), sep="\t"),
        metadata_columns=header_cols[1:1 + num_meta_cols],
        warnings=warnings,
    )


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


def parse_delimited_file(
    content_text: str,
    file_ext: str,
    content_hash: str,
) -> ParsedDataset:
    """Parse CSV, TSV, or TXT matrix file."""
    delimiter = sniff_delimiter(content_text, file_ext)

    # Use pandas to read the entire table into memory (safely bounded)
    stream = io.StringIO(content_text)
    try:
        raw_df = pd.read_csv(
            stream,
            sep=delimiter,
            index_col=0,
            low_memory=False,
            encoding_errors="replace",
        )
    except Exception as e:
        raise DatasetParseError(f"Failed to parse delimited scientific matrix: {str(e)}")

    if raw_df.empty:
        raise DatasetParseError("The uploaded scientific matrix contains no data.")

    first_col_name = str(raw_df.index.name or "Feature_ID")

    # Assess orientation
    orientation = assess_orientation(raw_df, first_col_name)

    # Build standardized numeric matrix: features (rows) x samples (columns)
    warnings = []
    if orientation.detected_orientation == "samples_as_rows":
        # Rows are samples, columns are features -> transpose for standard internal matrix
        work_df = raw_df.T
        num_features = len(work_df)
        num_samples = len(work_df.columns)
        feature_ids = [str(x) for x in work_df.index]
        sample_ids = [str(x) for x in work_df.columns]
    else:
        # Standard: rows are features, columns are samples
        work_df = raw_df.copy()
        num_features = len(work_df)
        num_samples = len(work_df.columns)
        feature_ids = [str(x) for x in work_df.index]
        sample_ids = [str(x) for x in work_df.columns]

    # Convert non-numeric cells to NaN
    numeric_df = work_df.apply(pd.to_numeric, errors="coerce")

    # Check for duplicate feature or sample IDs
    if len(feature_ids) != len(set(feature_ids)):
        dup_count = len(feature_ids) - len(set(feature_ids))
        warnings.append(f"Found {dup_count} duplicate feature identifiers. Indices were disambiguated.")
        # Disambiguate duplicate feature IDs
        numeric_df.index = [
            f"{feat}_{i}" if count > 1 else feat
            for i, (feat, count) in enumerate(
                zip(numeric_df.index, pd.Series(numeric_df.index).map(pd.Series(numeric_df.index).value_counts()))
            )
        ]
        feature_ids = list(numeric_df.index)

    if len(sample_ids) != len(set(sample_ids)):
        dup_sample_count = len(sample_ids) - len(set(sample_ids))
        warnings.append(f"Found {dup_sample_count} duplicate sample identifiers.")

    file_format_name = "TSV" if delimiter == "\t" else ("CSV" if delimiter == "," else "TXT")

    return ParsedDataset(
        file_format=file_format_name,
        content_hash=content_hash,
        delimiter=delimiter,
        total_raw_rows=len(raw_df),
        total_raw_cols=len(raw_df.columns) + 1,
        num_features=num_features,
        num_samples=num_samples,
        feature_ids=feature_ids,
        sample_ids=sample_ids,
        orientation=orientation,
        numeric_matrix=numeric_df,
        raw_preview_df=raw_df.head(60),
        metadata_columns=[],
        warnings=warnings,
    )


def parse_scientific_dataset(content_bytes: bytes, original_filename: str) -> ParsedDataset:
    """
    Main entry point for scientific dataset ingestion and orientation assessment.
    Performs security boundaries, encoding detection, parsing, and matrix validation.
    """
    file_size = len(content_bytes)
    if file_size == 0:
        raise DatasetParseError("The uploaded file is empty (0 bytes).")
    if file_size > MAX_FILE_SIZE_BYTES:
        raise DatasetParseError(
            f"File size ({file_size / (1024*1024):.1f} MB) exceeds maximum allowed limit of {MAX_FILE_SIZE_BYTES / (1024*1024):.0f} MB."
        )

    content_hash = compute_sha256(content_bytes)
    encoding = detect_encoding(content_bytes)
    content_text = content_bytes.decode(encoding)

    _, ext = os.path.splitext(original_filename.lower())
    clean_ext = ext.strip()

    if clean_ext == ".gct" or content_text.startswith("#1.2") or content_text.startswith("#1.3"):
        return parse_gct_file(content_text, content_hash)

    if clean_ext in [".csv", ".tsv", ".txt"]:
        return parse_delimited_file(content_text, clean_ext, content_hash)

    raise DatasetParseError(f"Unsupported file format '{clean_ext}'. Supported formats are CSV, TSV, TXT, and GCT.")

