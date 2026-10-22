# Visibility Scoring

**Visibility Scoring** (sidebar `N` > **FSS Tools** > **UV Tools** > **Packing** > **Visibility Scoring**) analyses how much of each mesh and UV island is visible from reference cameras (such as the pilot and copilot viewpoints) across animation states.

The analysis writes its results to an external compressed file, `<blend_name>.visibility`, beside the `.blend` file. It modifies no meshes, leaves no custom properties on exported objects, and does not alter glTF exports. The results are used by the **Heatmap** (Visibility mode) for visual review and will guide the automatic UV packer to distribute texel density where it matters most.

---

## Why Visibility Scoring?

Texture space in MSFS is limited. Geometry positioned in plain sight of the flight crew—such as the glareshield, primary flight instruments, and main throttle pedestal—requires sharp, legible resolution. Geometry occluded beneath seats, buried behind sidewall structures, or facing away from the cockpit cameras does not warrant high texel density.

The Visibility analyzer computes the solid angle of every face relative to the reference cameras:
- **Distance Invariance:** Geometry at 0.5 m and 2.0 m receives identical visibility scores when unoccluded. Knobs and circuit breakers in plain view score as high as large bulkheads.
- **Directional Weighting:** Faces directly in front of the camera receive full weight ($1.0$). As the view angle deviates from camera forward, weight falls off smoothly down to a configurable floor ($0.2$ default at $\ge 90^\circ$).
- **Animation Coverage:** Lever, yoke, and switch animations are sampled across $2$ to $10$ animation steps, preventing parts revealed by moving controls from being misclassified as occluded.
- **Loose Parts and Decals:** Decals and glass do not occlude underlying opaque surfaces. Invisible collision and occlusion primitives are excluded from evaluation.
- **Islands from Seen Faces:** at packing, an island's value comes from its seen faces only, so a partly hidden island keeps the density its visible part needs. The scores belong to faces, so new seams or a new unwrap need no update.
- **Hierarchy Resolution:** Millimeter-scale fasteners and switches smaller than the raster resolution inherit visibility from their parent assembly, preventing false negatives.

---

## Settings

The settings are saved with the `.blend` file in `Scene.fss_visibility`:

### Reference Cameras
A dynamic list synchronised with the scene cameras:
- **Include:** Checkbox enabling the camera for analysis.
- **Mode:**
  - **Look Around (Default):** Evaluates a full $360^\circ$ spherical cubemap around the camera location, weighted by angle from the camera's default forward vector. Designed for pilot and copilot viewpoints where the flight crew can turn their heads.
  - **Fixed View:** Evaluates a single frustum matching the camera's focal length and sensor aspect ratio (at $2560 \times 1440$ resolution). Only what lies inside the camera's own frame counts, at full weight; use it for a view whose direction cannot change.

### Animation Steps
- **Animation Steps:** Slider from $2$ to $10$ (default $5$). Evenly samples actions and NLA tracks across their duration:
  - 2 steps: $0\%$ and $100\%$
  - 3 steps: $0\%$, $50\%$, and $100\%$
  - 5 steps: $0\%$, $25\%$, $50\%$, $75\%$, and $100\%$

### Advanced Settings
Expand **Advanced Settings** to inspect or fine-tune algorithmic parameters:
- **Direction Floor (0.2):** Minimum solid angle weight assigned to peripheral and backward angles.
- **Falloff (1.0):** Power applied to the cosine of the angle from the camera's forward direction.
- **Cube Resolution (1,024 px):** Resolution per face of the cubemap passes ($6 \times 1024 \times 1024$).
- **Pixel Threshold (10 px):** Minimum footprint threshold below which geometry is classified as undetermined and resolved via scene hierarchy.

> [!NOTE]
> Modifying Cube Resolution or Pixel Threshold alters baseline scores. Maintain default values unless instructed by project leads.

---

## Workflow: Updating Visibility

1. **Save your file:** The analysis writes `<blend_name>.visibility` to disk. If the `.blend` is unsaved, the operator is disabled.
2. **Select reference cameras:** Ensure at least one camera (e.g. `CAM_PILOT` or `CAM_COPILOT`) has **Include** checked.
3. **Click Update Visibility:**
   - In interactive Blender, the operator runs modally. Progress is displayed in the window status bar (e.g. `FSS Visibility: State 50%, Camera 'CAM_PILOT' (4/10)...`).
   - Pressing `Esc` cancels the analysis cleanly and writes nothing to disk.
   - The scene state (active frame, action assignments, NLA tracks, and temporary mesh attributes) is restored exactly, even if cancelled or on errors.
4. **Review Results:**
   - A summary is displayed directly in the panel header and statistics table.
   - A detailed breakdown is written to the **FSS Visibility Report** Text datablock in Blender's Text Editor.

---

## Panel Report & Inspection Tools

After an analysis run, the panel displays:
- **File Metadata:** Timestamp of the `.visibility` file, camera names, and animation state count.
- **Surface Breakdown:** Total faces, surface area ($m^2$), and overall scored meshes.
- **Never-Seen Objects & Islands:** Number of objects and UV islands with a score of $0.000$ (never visible from any included camera in any state).
  - Click **Select Never Seen** to select them for review. They need no density mark: never-seen faces get the minimum density automatically. Check whether they are really never visible: switch positions and parts shown only under some conditions may not be seen in the analysed states. Nothing is deleted.
- **Undetermined Objects:** Small sub-pixel parts whose scores were inherited from parent panels.
- **Stale Meshes Warning:** If geometry is modified, subdivided, or deleted after visibility data was generated, the panel alerts: `Mesh geometry changed since last run`.
  - Click **Select Stale** to select affected objects that need updating.

---

## Visualizing Visibility: The Heatmap

To visualize visibility directly on the 3D model:
1. Open sidebar `N` > **FSS Tools** > **Utilities** > **Heatmap**.
2. Enable **Show Heatmap**.
3. Set **Mode** to **Visibility**.

### Color Legend
- **Blue side ($0.5$ to $1.0$):** High visibility in plain view of the cameras.
- **Neutral Grey ($0.5$):** Moderate visibility or peripheral coverage.
- **Red side ($0.0$ to $0.5$):** Low visibility, grazing angles, or heavily occluded.
- **Magenta:** Never seen ($0.000$ score across all cameras and animation steps).
- **Cyan:** Undetermined sub-pixel geometry whose score was inherited from parent structures.
- **Dark Grey (No Data):** Objects not present in the `.visibility` file or whose mesh geometry has become stale.
