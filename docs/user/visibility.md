# Visibility Scoring

**Visibility Scoring** (sidebar `N` > **FSS MSFS Tools** > **UV Auto Packing** > **Visibility Scoring**) lights the
model with probe lights you place in the scene, for the cockpit at the pilot's and copilot's heads, and measures how
bright each face gets, over the animation steps. Bright faces are the ones the crew sees well; faces in shadow or far
away get less texture.

The results go to a file beside the `.blend`, `<blend_name>.visibility`. The analysis changes no mesh, leaves nothing on
the exported objects, and does not change the glTF. The **Heatmap** (Visibility mode) shows the results, and **Pack**
uses them to share out texel density.

---

## What the Score Means

- **What you see in the viewport is what is measured.** A face's score follows the brightness the probe lights give it
  in the viewport, in **Rendered** shading with the world light off, a white material and **View Transform Standard**:
  light power, distance, the spot's cone and its soft edge, the area light's angle, and shadows, soft ones included.
  The values are measured against EEVEE and agree within a few percent.
- **The score is a multiplier from 0 to 1.** All scores are scaled so the most visible island is 1.0. That island gets
  the full density its marks allow (zone, parents, object); an island at 0.4 gets 0.4 of it.
- **An island takes the value of its well-lit part.** Its faces are ranked by brightness, by area, and the island takes
  the value that the share set in **Island Value** stays below (90 % by default). An island half in a shadow keeps the
  value of its lit half.
- **Islands that touch on the model do not jump.** When an island is more than the **Step Limit** times darker than
  an island it touches, it rises to the brighter one divided by the Step Limit, so a seam does not show a sudden
  change of texel density. No island is ever lowered: a lit island keeps its value, and the darker parts around it
  get more. The rise travels on: a neighbour of a 1.0 island gets at least 0.67, its neighbour 0.44, and so on.
- **Nothing scores below the Ambient.** Every face gets the **Ambient** (0.1 by default) as if lit by a faint light
  from everywhere: a score is the Ambient plus the rest of the way to 1 in proportion to the probe lights' brightness.
  Faces no probe light reaches score exactly the Ambient, so they keep a tenth of the density.
- **Animation:** levers, the yoke, doors and the probe lights themselves are sampled over the animation steps. A face
  takes its brightest step, so a part revealed by a moving control, or lit by a light that sweeps, keeps that value.
- **Loose parts and decals:** decals and glass do not cast shadows on what is under them. Objects with an invisible
  material (collision, clickspots) are left out.
- **Small parts** (screws, small labels) too small to measure take the value of the part they belong to.
- The scores belong to faces, so new seams or a new unwrap need no update.

---

## Setting Up the Probe Lights

1. Add point, spot or area lights where the crew's eyes are, for example under an empty `VISIBILITY_PROBE_LIGHTS`. A
   spot pointing forward with a wide cone (120°) lights what the pilot looks at; a point light lights all around.
2. Animate them if the head turns: a spot that sweeps from 45° outboard to 45° inboard over the animation lights
   everything along the sweep.
3. **Preview** what they light: viewport shading **Rendered** with **Scene World** on in the shading popover, the
   world light off (**World** properties > **Surface** > **Strength** 0), and in **Color Management** the **View
   Transform** **Standard**, **Exposure** 0. Override the material with a white one (**View Layer** > **Override** > **Material**),
   or judge on the model's own colours. White in this preview is what scores 1.0 before the scaling; soft shadows show
   as in the scoring.
4. Keep the lights out of the export: tag them (or the empty above them) and turn on the tag's **No Export** mark in
   [Tags](fss-tools.md#tags).

Sun lights have no position and do not count; the list warns when one is included.

---

## Settings

The settings are saved with the `.blend` file:

### Probe Lights

The list follows the scene's lights by itself (added, renamed, deleted). Each row has:

- **Include:** the light is a probe light.
- The light's name and type icon, and the **select** button (arrow), which selects the light in the viewport.
- The light's type, power and spot cone, for example `Spot 5 W 120°`.

### Main Settings

- **Animation Steps** (2 to 10, default 5): steps evenly spaced over each animation's length. 2 gives 0 % and 100 %,
  5 gives 0, 25, 50, 75 and 100 %.
- **Island Value** (50 to 100 %, default 90 %): what an island takes from its faces, see above. 50 % is the median
  face, 100 % its brightest face.
- **Ambient** (0 to 0.5, default 0.1): the lowest score any face or island can have; see above. Pack never goes below
  it, **Partly Seen Islands** included.
- **Step Limit** (1 to 4, default 1.5): how many times brighter one island may be than an island it touches; the
  darker one rises. 1 makes
  touching islands equal.

### Advanced Settings

- **Shadow Samples** (default 4): points spread over each light's **Radius** that the shadows are measured from, for
  the soft shadows. A light with **Radius** 0 uses one point and casts hard shadows. Each sample costs time.
- **Cube Resolution** (1,024 px) and **Min Threshold** (10 px): how finely the shadows are measured, and below which
  size a part counts as too small to measure.

> [!NOTE]
> Changing Cube Resolution or Min Threshold changes the scores. Keep the defaults unless the project lead says
> otherwise.

---

## Workflow: Updating Visibility

1. **Save the file:** the analysis writes `<blend_name>.visibility` beside it. Until the `.blend` is saved, the button
   is greyed out.
2. **Include** at least one probe light.
3. **Click Update Visibility:**
   - A progress bar replaces the button while it runs.
   - `Esc` cancels; nothing is written.
   - The scene (current frame, animations, lights) is put back as it was, also after a cancel or an error.
4. **Read the results** in the panel and in the Text Editor's **FSS Visibility Report**: the lights and their positions
   per step, the brightest face, what the step limit changed, and the scores per area.

---

## Panel Report

After a run, the panel shows:

- **File:** when the `.visibility` file was written, the lights used and the number of views (steps × lights × shadow
  samples). A note shows when the settings have changed since.
- **Never Seen:** objects and islands that no probe light reaches in any step. **Select Never Seen** selects them. They
  need no mark: they score the **Ambient** (x0.10 by default), the lowest score there is.
  Check whether they are really never visible: switch positions and parts shown only in some conditions may not be lit
  in the analysed steps. Nothing is deleted.
- **Undetermined:** small parts that took the value of the part they belong to.
- **Stale:** meshes changed since the run. **Select Stale** selects them; run **Update Visibility** again.
- **Scored by an older version:** a file made by the earlier camera-based scoring. The packer does not use it; run
  **Update Visibility** again.

---

## Visualizing Visibility: The Heatmap

1. Open sidebar `N` > **FSS Tools** > **Heatmap**.
2. Turn on **Show Heatmap**.
3. Set **Mode** to **Visibility**.

### Color Legend

- **Blue side (0.5 to 1.0):** well lit by the probe lights.
- **Neutral grey (0.5):** half as bright as the most visible island.
- **Red side (0.0 to 0.5):** dim: far away, at a grazing angle, or in shadow.
- **Magenta:** never lit in any step.
- **Cyan:** a part too small to measure that took its parent's value.
- **Dark grey (no data):** objects not in the `.visibility` file, or changed since.
