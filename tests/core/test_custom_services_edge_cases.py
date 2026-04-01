import os
import sys

sys.path.insert(0, os.getcwd())

from handlers.custom_services import (
    _allowed_move_directions,
    _children_customer_rows,
    _children_grid_preview_rows,
)


def test_allowed_move_directions_boundaries():
    # top-left
    assert _allowed_move_directions(0) == ["down", "right"]
    # middle first row
    assert _allowed_move_directions(1) == ["down", "left", "right"]
    # first item second row
    assert _allowed_move_directions(3) == ["up", "down", "right"]


def test_children_rows_keep_positions_for_sparse_grid():
    children = [
        {"_id": "a", "name": "A", "position": 0},
        {"_id": "b", "name": "B", "position": 2},
        {"_id": "c", "name": "C", "position": 4},
    ]
    grid_rows = _children_grid_preview_rows(children)
    customer_rows = _children_customer_rows(children)

    assert len(grid_rows) >= 2
    assert len(grid_rows[0]) == 3
    # Customer view should collapse empty slots but keep ordering.
    first_row_labels = [btn.text for btn in customer_rows[0]]
    assert first_row_labels == ["A", "B"]
