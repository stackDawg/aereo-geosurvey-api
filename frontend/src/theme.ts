// Map colours. The map is drawn on a light street basemap in both themes, so these do not switch
// with the page theme.

/** Sequential blue ramp (steps 200 → 700): polygon area, small → large. */
export const AREA_RAMP = ["#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];
export const AREA_OUTLINE = "#0d366b";
/** Lines are a second series, so they take the next categorical hue (orange). */
export const LINE_COLOR = "#eb6834";
export const POINT_COLOR = "#52514e";
/** Features that have geometry but no measurement (failed or unsupported). */
export const NOT_MEASURED_COLOR = "#898781";
export const SELECTED_COLOR = "#0b0b0b";
export const HALO_COLOR = "#ffffff";
