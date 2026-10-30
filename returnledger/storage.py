"""Export (CSV / JSON / SQL / SQLite), typed loading, ground truth and the source manifest."""
import csv
import hashlib
import json
import os
import platform
import sqlite3
from datetime import date, datetime

from . import __version__
from . import config as C
from .money import fmt, parse
from .schema import TABLES, TABLE_BY_NAME, ENUMS

GT_ANOMALY_COLS = ["anomaly_id", "issue_type", "entity_type", "entity_id", "rma_id", "related_ids",
                   "expected_value", "recorded_value", "injected_at_step", "description"]
GT_LABEL_COLS = ["return_line_id", "rma_id", "decision_recorded", "expected_line_decision", "expected_approved_qty",
                 "expected_decision_reason", "expected_override_applied", "expected_disposition",
                 "expected_line_refund_amount", "is_anomaly", "anomaly_issue_types"]

# Constraints that the per-column definitions cannot express.
EXTRA_SQL_CONSTRAINTS = {
    "inspection": ["FOREIGN KEY (shipment_id, return_line_id) REFERENCES shipment_line (shipment_id, return_line_id)"
                   " DEFERRABLE INITIALLY DEFERRED"],
}


# ------------------------------------------------------------------ conversions
def to_text(value, typ):
    if value is None:
        return ""
    if typ == "DECIMAL":
        return fmt(value)
    if typ == "RATE":
        return f"{value // 10000}.{value % 10000:04d}"
    if typ == "BOOLEAN":
        return "true" if value else "false"
    if typ == "TIMESTAMP":
        return value.isoformat(timespec="seconds")
    if typ == "DATE":
        return value.isoformat()
    return str(value)


def from_text(text, typ):
    if text == "" or text is None:
        return None
    if typ == "DECIMAL":
        return parse(text)
    if typ == "RATE":
        whole, _, frac = text.partition(".")
        return int(whole) * 10000 + int((frac + "0000")[:4])
    if typ == "BOOLEAN":
        return text == "true"
    if typ == "TIMESTAMP":
        return datetime.fromisoformat(text)
    if typ == "DATE":
        return date.fromisoformat(text)
    if typ == "INTEGER":
        return int(text)
    return text


def to_json(value, typ):
    if value is None:
        return None
    if typ == "DECIMAL":
        return round(value / 100, 2)
    if typ == "RATE":
        return round(value / 10000, 4)
    if typ in ("TIMESTAMP", "DATE"):
        return to_text(value, typ)
    return value


def _sql_literal(value, typ):
    if value is None:
        return "NULL"
    if typ == "BOOLEAN":
        return "TRUE" if value else "FALSE"
    if typ in ("DECIMAL", "RATE", "INTEGER"):
        return to_text(value, typ)
    return "'" + to_text(value, typ).replace("'", "''") + "'"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------------- DDL
SQL_TYPES = {"TEXT": "TEXT", "INTEGER": "INTEGER", "DECIMAL": "NUMERIC(12,2)", "RATE": "NUMERIC(6,4)",
             "DATE": "DATE", "TIMESTAMP": "TIMESTAMP", "BOOLEAN": "BOOLEAN"}


def ddl():
    out = ["-- ReturnLedger schema (generated from returnledger/schema.py). ANSI-style SQL; tested on SQLite.",
           "-- Foreign keys are DEFERRABLE so the exchange-order <-> RMA cycle can be loaded in one transaction.", ""]
    for t in TABLES:
        cols = []
        for f in t.fields:
            line = f"    {f.name} {SQL_TYPES[f.type]}"
            if f.required:
                line += " NOT NULL"
            if f.unique and t.pk != [f.name]:
                line += " UNIQUE"
            if f.enum:
                allowed = ", ".join(f"'{v}'" for v in ENUMS[f.enum])
                line += f" CHECK ({f.name} IN ({allowed}))"
            cols.append(line)
        cols.append(f"    PRIMARY KEY ({', '.join(t.pk)})")
        for f in t.fields:
            if f.fk:
                ref_table, ref_col = f.fk.split(".")
                cols.append(f"    FOREIGN KEY ({f.name}) REFERENCES {ref_table} ({ref_col}) DEFERRABLE INITIALLY DEFERRED")
        cols.extend("    " + c for c in EXTRA_SQL_CONSTRAINTS.get(t.name, []))
        out.append(f"-- {t.entity}: {t.desc}")
        out.append(f"CREATE TABLE {t.name} (\n" + ",\n".join(cols) + "\n);\n")
    return "\n".join(out)


# ----------------------------------------------------------------------- export
def export(gen, out_dir, formats=("csv", "json", "sql", "sqlite"), command=""):
    os.makedirs(out_dir, exist_ok=True)
    files = []

    def track(path, rows):
        files.append({"path": os.path.relpath(path, out_dir).replace("\\", "/"), "rows": rows,
                      "bytes": os.path.getsize(path), "sha256": _sha256(path)})

    if "csv" in formats:
        d = os.path.join(out_dir, "csv")
        os.makedirs(d, exist_ok=True)
        for t in TABLES:
            path = os.path.join(d, f"{t.name}.csv")
            with open(path, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh, lineterminator="\n")
                w.writerow(t.columns)
                types = [f.type for f in t.fields]
                for r in gen.t[t.name]:
                    w.writerow([to_text(r[c], ty) for c, ty in zip(t.columns, types)])
            track(path, len(gen.t[t.name]))

    if "json" in formats:
        d = os.path.join(out_dir, "json")
        os.makedirs(d, exist_ok=True)
        for t in TABLES:
            path = os.path.join(d, f"{t.name}.json")
            rows = [{f.name: to_json(r[f.name], f.type) for f in t.fields} for r in gen.t[t.name]]
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n]\n")
            track(path, len(rows))

    if "sql" in formats:
        d = os.path.join(out_dir, "sql")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "schema.sql")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(ddl())
        track(path, len(TABLES))
        path = os.path.join(d, "seed.sql")
        total = 0
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("-- ReturnLedger seed data. Load schema.sql first.\nBEGIN;\n")
            for t in TABLES:
                rows = gen.t[t.name]
                total += len(rows)
                for i in range(0, len(rows), 500):
                    values = ",\n".join("(" + ", ".join(_sql_literal(r[f.name], f.type) for f in t.fields) + ")"
                                        for r in rows[i:i + 500])
                    fh.write(f"INSERT INTO {t.name} ({', '.join(t.columns)}) VALUES\n{values};\n")
            fh.write("COMMIT;\n")
        track(path, total)

    gt_dir = os.path.join(out_dir, "ground_truth")
    os.makedirs(gt_dir, exist_ok=True)
    path = os.path.join(gt_dir, "ground_truth_anomalies.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, GT_ANOMALY_COLS, lineterminator="\n")
        w.writeheader()
        w.writerows(gen.gt_anomalies)
    track(path, len(gen.gt_anomalies))
    path = os.path.join(gt_dir, "ground_truth_anomalies.json")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(gen.gt_anomalies, fh, indent=1)
        fh.write("\n")
    track(path, len(gen.gt_anomalies))
    path = os.path.join(gt_dir, "ground_truth_labels.csv")
    labels = [gen.gt_labels[k] for k in sorted(gen.gt_labels)]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(GT_LABEL_COLS)
        for lab in labels:
            row = []
            for c in GT_LABEL_COLS:
                v = lab[c]
                if c == "expected_line_refund_amount":
                    v = fmt(v)
                elif isinstance(v, bool):
                    v = "true" if v else "false"
                row.append("" if v is None else v)
            w.writerow(row)
    track(path, len(labels))

    if "sqlite" in formats:
        build_sqlite(out_dir, os.path.join(out_dir, "csv"))

    manifest = {
        "project": "ReturnLedger",
        "generator": "returnledger.generator",
        "generator_version": __version__,
        "command": command,
        "seed": gen.seed,
        "scale": gen.scale,
        "as_of": C.AS_OF.isoformat(),
        "order_date_range": [C.ORDER_START.isoformat(), C.ORDER_END.isoformat()],
        "target_volume": {"orders": gen.n_orders, "return_requests": gen.n_requests, "return_lines": gen.n_lines},
        "injected_anomalies": gen.anomaly_counts,
        "row_counts": {t.name: len(gen.t[t.name]) for t in TABLES},
        "provenance": {
            "external_data_used": False,
            "statement": "All records are synthetic, produced by a seeded pseudo-random generator. No real "
                         "customers, orders or payment data were used. Names are random combinations of common "
                         "first/last names; emails use the reserved example.com domain; tax rates are "
                         "illustrative. Public material informed the schema only (general retail returns practice).",
            "license": "Synthetic data and code released under the MIT License (see LICENSE).",
        },
        "files": files,
    }
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    return manifest


def build_sqlite(out_dir, csv_dir):
    path = os.path.join(out_dir, "returnledger.db")
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.executescript(ddl())
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("BEGIN")
    for t in TABLES:
        with open(os.path.join(csv_dir, f"{t.name}.csv"), newline="", encoding="utf-8") as fh:
            rd = csv.reader(fh)
            next(rd)
            bools = [f.type == "BOOLEAN" for f in t.fields]
            rows = [[(None if v == "" else (1 if v == "true" else 0) if b else v) for v, b in zip(row, bools)]
                    for row in rd]
        con.executemany(f"INSERT INTO {t.name} VALUES ({', '.join('?' * len(t.fields))})", rows)
    con.commit()
    con.close()
    return path


# ------------------------------------------------------------------------- load
def load_tables(data_dir):
    tables = {}
    for t in TABLES:
        with open(os.path.join(data_dir, "csv", f"{t.name}.csv"), newline="", encoding="utf-8") as fh:
            rd = csv.DictReader(fh)
            types = {f.name: f.type for f in t.fields}
            tables[t.name] = [{k: from_text(v, types[k]) for k, v in row.items()} for row in rd]
    return tables


def load_ground_truth(data_dir):
    with open(os.path.join(data_dir, "ground_truth", "ground_truth_anomalies.csv"), newline="", encoding="utf-8") as fh:
        anomalies = list(csv.DictReader(fh))
    with open(os.path.join(data_dir, "ground_truth", "ground_truth_labels.csv"), newline="", encoding="utf-8") as fh:
        labels = list(csv.DictReader(fh))
    return anomalies, labels


def write_csv(path, rows, cols):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, cols, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=2, default=str)
        fh.write("\n")


def environment():
    return {"python": platform.python_version(), "platform": platform.platform()}


__all__ = ["export", "load_tables", "load_ground_truth", "ddl", "build_sqlite", "TABLE_BY_NAME"]
