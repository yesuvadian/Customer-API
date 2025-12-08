from datetime import datetime

def process_row_data(row, id_fields_to_keep):

    columns, values = [], []

    for col, val in row.items():

        if not col or not col.strip():
            continue

        if val is None and col not in id_fields_to_keep:
            continue

        if isinstance(val, str):
            try:
                val = datetime.strptime(val, "%Y-%m-%d").date()
            except:
                pass

        columns.append(f'"{col}"')
        values.append(val)

    return columns, values
