# Tabular database map

imr-sqliblind can represent discovered schemas, tables, columns and bounded row values as real tables in the web console or as standalone reports.

## Web console

Open the **Tables** result tab after selecting or starting a scan.

The view shows one card per `schema.table` with:

- the qualified table name and current entity status
- an ordinal column inventory
- extracted row values when bounded data extraction was enabled
- horizontal scrolling for wide tables
- the same global entity filter used by the other result views

Rendering is lazy. The browser only materializes the table cards while the **Tables** tab is visible or while an HTML table report is being exported.

The export selector includes:

- `tables · ASCII text`
- `html-tables · HTML table report`

Both browser exports are generated from the current session snapshot and do not start additional inference requests.

## CLI ASCII export

```bash
sqliblind \
  --url 'https://authorized-lab.example/fetch' \
  --parameter id \
  map --format tables --output database-map.txt
```

The report uses only `+`, `-` and `|` for table borders. Long values are flattened to one line and clipped to keep the report within a bounded width.

## CLI HTML table export

```bash
sqliblind \
  --url 'https://authorized-lab.example/fetch' \
  --parameter id \
  map --format html-tables --output database-map.html
```

The HTML report is self-contained, responsive and filterable. It does not load external scripts, styles, fonts or images. Entity names and extracted values are HTML-escaped before rendering.

## Special characters

Names and values containing `%` or `_` are displayed literally. The table renderer does not issue SQL requests and does not interpret these characters as `LIKE` operators.
