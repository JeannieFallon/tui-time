# Recording Demo GIFs

How to capture a TUI app running and turn it into a GIF for its
README. Done on the Mac, not the Debian VM.

## 1. Set up the pane

- Run the app in your terminal as usual.
- Size the pane to something reasonable. Around 80x24 reads well in
  a README.
- Let it run a second or two so it's in steady state before you
  record.

## 2. Record

1. Press **Cmd+Shift+5**. A toolbar appears at the bottom of the
   screen.
2. The toolbar has two groups of buttons. The left three are
   screenshots. The next two are video. Click the second video
   button: **Record Selected Portion** (dashed box with a small
   circle).
3. Drag the selection box tightly around the terminal pane. Leave
   out window chrome.
4. The button on the right should now say **Record**. Click it.
5. Let it run 5 to 8 seconds.
6. Stop: click the **stop button in the menu bar** (circle with a
   square inside, near the clock), or press **Cmd+Control+Esc**.
   If the menu bar is hidden, move the mouse to the top edge.

The recording saves to the Desktop as a `.mov`.

The toolbar remembers the last mode. If **Cmd+Shift+5** shows
**Capture** instead of **Record**, you're in a screenshot mode.
Switch to the video button first.

If the toolbar never appears, use **QuickTime Player, File, New
Screen Recording**. It opens the same toolbar.

## 3. Convert to GIF

Uses **Gifski**, free from the Mac App Store.

1. Open Gifski and drag the `.mov` onto its window.
2. Set width to around 800.
3. Set FPS to 10 to 15. Plenty for a terminal app.
4. **Convert**, then **Save**.

Check the size in Finder. Aim for under 3 MB. If it's larger,
convert again with a smaller width or lower FPS.

## 4. Get it into the repo

The GIF is on the Mac. The repo is on the VM. Copy it over from a
Mac terminal:

    scp ~/Desktop/<file>.gif <vm-host>:<repo-path>/apps/<class>/<app>/demo-<variant>.gif

Naming: `demo.gif` for a single demo, `demo-<variant>.gif` when
there's one per theme or mode, e.g. `demo-night.gif`.

## 5. Embed

In the app's README:

    ![clock, night theme](demo-night.gif)

Relative path, since the GIF sits next to the README.

Commit:

    git add apps/<class>/<app>/demo-*.gif apps/<class>/<app>/README.md
    git commit -m "<app>: add demo GIF"

## Notes

- **One GIF per variant** beats one long GIF cycling through them.
  Smaller files, and each one shows up next to the text describing
  it.
- **Not reproducible.** When the app changes, re-record by hand. If
  that gets tedious, VHS (charmbracelet/vhs) renders GIFs from a
  script file on the VM and can be re-run anytime.
