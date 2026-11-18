import json
import os


def load_grid_config(path):
    """Load and validate the grid automation JSON file."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Grid config file does not exist: {path}")

    with open(path) as f:
        raw = json.load(f)

    required_keys = ("initial_z", "r", "x_map", "y_map", "z_distance_map")
    for key in required_keys:
        if key not in raw:
            raise ValueError(f"Missing '{key}' in grid config")

    z_distance_map = {}
    for z, distance in raw["z_distance_map"].items():
        z_distance_map[round(float(z), 4)] = str(distance)

    x_rows = []
    for x, row_config in raw["x_map"].items():
        if "row" not in row_config:
            raise ValueError(f"Each X entry must contain 'row'. Problematic X: {x}")

        x_rows.append({
            "x": float(x),
            "row": str(row_config["row"]),
        })

    y_columns = []
    for y, column_config in raw["y_map"].items():
        if "column" not in column_config or "z_values" not in column_config:
            raise ValueError(f"Each Y entry must contain 'column' and 'z_values'. Problematic Y: {y}")

        z_values = [round(float(z), 4) for z in column_config["z_values"]]
        if not z_values:
            raise ValueError(f"Missing z_values for Y={y}")

        for idx in range(1, len(z_values)):
            if z_values[idx] >= z_values[idx - 1]:
                raise ValueError(f"z_values for Y={y} must go down from the first value to the last value")

        for z in z_values:
            if z not in z_distance_map:
                raise ValueError(f"Missing distance label for Z={z}")

        y_columns.append({
            "y": float(y),
            "column": str(column_config["column"]),
            "z_values": z_values,
        })

    if not x_rows:
        raise ValueError("Grid config must contain at least one X row")
    if not y_columns:
        raise ValueError("Grid config must contain at least one Y column")

    initial_z = float(raw["initial_z"])
    max_grid_z = max(z for column in y_columns for z in column["z_values"])
    if initial_z <= max_grid_z:
        raise ValueError("initial_z must be higher than every measurement Z")

    return {
        "initial_z": initial_z,
        "r": float(raw["r"]),
        "z_distance_map": z_distance_map,
        "x_rows": x_rows,
        "y_columns": y_columns,
    }


def grid_point_name(column, row, z, z_distance_map):
    return f"{column}{row}_{z_distance_map[round(float(z), 4)]}"


def grid_safe_position(x, y, grid_config):
    return (x, y, grid_config["initial_z"], grid_config["r"])


def grid_point_position(x, y, z, grid_config):
    return (x, y, z, grid_config["r"])


def count_grid_points(grid_config):
    z_count = sum(len(column["z_values"]) for column in grid_config["y_columns"])
    return z_count * len(grid_config["x_rows"])
