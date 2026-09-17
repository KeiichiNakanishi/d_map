# Disney Simple Maps

Contents:
- `tdl_map.png`: simplified Tokyo Disneyland map
- `tdl_spots.json`: normalized point data corresponding to `tdl_map.png`
- `tds_map.png`: simplified Tokyo DisneySea map
- `tds_spots.json`: normalized point data corresponding to `tds_map.png`

## Coordinate system

The top-left of each image is `(0, 0)`, the bottom-right is `(1, 1)`.

Example:
```js
marker.style.left = `${spot.x * 100}%`;
marker.style.top  = `${spot.y * 100}%`;
```

The PNG dimensions are currently 1491 x 1055 px.

## Scope

This first version contains:
- attractions
- main entrance
- restroom points
- area metadata

Coordinates are intentionally approximate and are matched to the simplified schematic maps, rather than GPS coordinates.
