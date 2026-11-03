// Compare: two panels side by side (wrong versus right, before versus after, naive versus improved).
// Each panel is a small world (its own, or the episode world continued with world "shared"),
// a table whose rows and marks change on cues, or text lines. A verdict badge lands on its word
// and only then colours the panels right and wrong, so the answer never shows early. State at a
// frame comes from compareState.ts (pure), which visibleText.ts also reads.
import { useMemo } from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { useEnterFrames, useEpisode } from "../context";
import { colors, fonts, radius, type } from "../theme";
import { clamp, easeOut } from "../time";
import type { SceneProps, World } from "../types";
import { bannerAt, compareClaimProblems, type ComparePanel, type CompareProps, panelStateAt, type RowState } from "./compareState";
import { Heading } from "./common";
import {
  COMPARE_GAP,
  COMPARE_HEADER_H,
  COMPARE_STAT_H,
  COMPARE_TITLE_H,
  COMPARE_VERDICT_H,
  compareBodySize,
  panelTableLayout,
  TABLE_CELL_GAP,
  TABLE_PAD_TOP,
  TABLE_PAD_X,
  tableProblems,
} from "./tableLayout";
import { tintColor, WorldCanvas } from "./world/WorldScene";
import { buildTimeline, fitCamera, localTimeline, ringInsetFilter, turnEnds, viewScale } from "./world/worldState";

export { fitCamera } from "./world/worldState";

export type { Banner, ComparePanel, CompareProps, PanelStep, TableRow } from "./compareState";

const GAP = COMPARE_GAP;
const HEADER_H = COMPARE_HEADER_H;
const STAT_H = COMPARE_STAT_H;
const VERDICT_H = COMPARE_VERDICT_H;
// W11b (judge v5, item 7): ring numerals and owner letters in a compare panel draw at 32 px or more.
export const PANEL_RING_TEXT_PX = 32;

// A banner (the verdict, then any later banners) lands on its word with zero lead and only then
// colours the panels right and wrong; a later banner can change the text, the winner and the pill
// labels, or hide the badge (text "") when the first verdict stops being true.
export const CompareScene: React.FC<SceneProps<CompareProps>> = ({ title, left, right, verdict, banners, fromFrame, sceneStartMs, sceneId, enter }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { manifest } = useEpisode();
  const enterFrames = useEnterFrames();
  const p = enter ? interpolate(frame, [0, enterFrames], [0, 1], { ...clamp, easing: easeOut }) : 1;
  const nowMs = ((fromFrame + frame) / fps) * 1000;
  const shared = useMemo(() => buildTimeline(manifest), [manifest]);
  const ends = useMemo(() => turnEnds(manifest), [manifest]);
  // W13b (Q05): a banner or stat whose written count disagrees with its claim stops the render.
  useMemo(() => {
    const bad = compareClaimProblems({ verdict, banners, left, right });
    if (bad.length) throw new Error(`Compare scene ${sceneId}: ${bad.join("; ")}`);
  }, [verdict, banners, left, right, sceneId]);

  const banner = bannerAt({ verdict, banners, left, right }, fromFrame, fps, frame);
  const v = banner === null ? 0 : interpolate(frame, [banner.at, banner.at + 12], [0, 1], { ...clamp, easing: easeOut });
  const winner = banner?.winner ?? "none";

  // Stage geometry (inside layout.stage, 1728 x 712).
  const headingH = title ? COMPARE_TITLE_H : 0;
  const { panelW, panelH } = compareBodySize(!!title);

  const tone = (side: "left" | "right"): "right" | "wrong" | null =>
    winner === "none" || v < 0.5 ? null : winner === side ? "right" : "wrong";

  return (
    <div style={{ position: "absolute", inset: 0, opacity: p }}>
      <div style={{ position: "absolute", left: 96, top: 124, width: 1728, height: 712, translate: `0px ${(1 - p) * 16}px` }}>
        {title ? <Heading text={title} /> : null}
        {(["left", "right"] as const).map((side, i) => (
          <Panel
            key={side}
            panel={side === "left" ? left : right}
            x={i * (panelW + GAP)}
            y={headingH}
            w={panelW}
            h={panelH}
            tone={tone(side)}
            toneP={v}
            pillLabel={banner && v >= 0.5 ? banner.labels[side] : undefined}
            nowMs={nowMs}
            frame={frame}
            fromFrame={fromFrame}
            fps={fps}
            sharedWorld={manifest.world ?? null}
            sharedTimeline={shared}
            sceneId={`${sceneId}-${side}`}
            sceneStartMs={sceneStartMs}
            turnEnds={ends}
            hasTitle={!!title}
          />
        ))}
        {banner && banner.text && v > 0 ? (
          <div
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              top: 712 - VERDICT_H,
              height: VERDICT_H,
              display: "flex",
              justifyContent: winner === "left" ? "flex-start" : winner === "right" ? "flex-end" : "center",
              alignItems: "center",
              opacity: v,
              translate: `0px ${(1 - v) * 14}px`,
            }}
          >
            <div
              style={{
                padding: "10px 30px",
                borderRadius: radius.card,
                background: colors.surfaceRaised,
                borderLeft: `8px solid ${winner === "none" ? colors.accent : colors.good}`,
                fontFamily: fonts.sans,
                fontSize: type.body,
                fontWeight: 800,
                color: colors.text,
                whiteSpace: "nowrap",
                maxWidth: 1728,
              }}
            >
              {banner.text}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
};

const Panel: React.FC<{
  panel: ComparePanel;
  x: number;
  y: number;
  w: number;
  h: number;
  tone: "right" | "wrong" | null;
  toneP: number;
  pillLabel?: string;
  nowMs: number;
  frame: number;
  fromFrame: number;
  fps: number;
  sharedWorld: World | null;
  sharedTimeline: ReturnType<typeof buildTimeline>;
  sceneId: string;
  sceneStartMs: number;
  turnEnds: Record<string, number>;
  hasTitle: boolean;
}> = ({ panel, x, y, w, h, tone, toneP, pillLabel, nowMs, frame, fromFrame, fps, sharedWorld, sharedTimeline, sceneId, sceneStartMs, turnEnds: ends, hasTitle }) => {
  const st = panelStateAt(panel, fromFrame, fps, frame);
  const statP = st.stat ? interpolate(frame, [st.stat.at, st.stat.at + 10], [0, 1], clamp) : 0;
  const titleP = st.titleAt === null ? 1 : interpolate(frame, [st.titleAt, st.titleAt + 10], [0, 1], clamp);
  const toneColor = tone === "right" ? colors.good : tone === "wrong" ? colors.bad : colors.line;
  const bodyH = h - HEADER_H - STAT_H - 12;
  const innerW = w - 12; // border-box: the thickest tone border (6 px) on both sides
  // A banner label replaces RIGHT / WRONG; with winner "none" it shows in a neutral pill.
  const pillText = pillLabel ?? tone ?? null;
  const pillColor = tone ? toneColor : colors.muted;

  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: w,
        height: h,
        boxSizing: "border-box",
        borderRadius: radius.card,
        background: colors.surface,
        border: `${tone ? 3 + 3 * toneP : 3}px solid ${toneColor}`,
        overflow: "hidden",
        fontFamily: fonts.sans,
      }}
    >
      <div style={{ height: HEADER_H, display: "flex", alignItems: "center", gap: 16, padding: "0 24px" }}>
        <div style={{ fontSize: type.body + 4, fontWeight: 800, color: colors.text, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", opacity: titleP }}>
          {st.title}
        </div>
        {st.tag ? <Pill text={st.tag} color={colors.muted} /> : null}
        <div style={{ flex: 1 }} />
        {pillText ? <Pill text={pillText} color={pillColor} opacity={toneP} /> : null}
      </div>
      <div style={{ position: "relative", height: bodyH, overflow: "hidden" }}>
        {panel.kind === "world" ? (
          <WorldPanel panel={panel} w={innerW} h={bodyH} nowMs={nowMs} sharedWorld={sharedWorld} sharedTimeline={sharedTimeline} sceneId={sceneId} sceneStartMs={sceneStartMs} turnEnds={ends} />
        ) : panel.kind === "table" ? (
          <TablePanel panel={panel} rows={st.rows} hasTitle={hasTitle} frame={frame} />
        ) : (
          <TextPanel lines={st.lines} frame={frame} />
        )}
      </div>
      <div style={{ height: STAT_H, boxSizing: "border-box", display: "flex", alignItems: "center", padding: "0 24px 16px" }}>
        {st.stat ? (
          <div
            style={{
              padding: "6px 20px",
              borderRadius: 12,
              background: colors.surfaceRaised,
              fontSize: type.body,
              fontWeight: 800,
              lineHeight: 1.1,
              color: colors.warn,
              opacity: statP,
              whiteSpace: "nowrap",
            }}
          >
            {st.stat.text}
          </div>
        ) : null}
      </div>
    </div>
  );
};

const Pill: React.FC<{ text: string; color: string; opacity?: number }> = ({ text, color, opacity = 1 }) => (
  <div
    style={{
      padding: "0px 14px",
      borderRadius: 999,
      border: `3px solid ${color}`,
      color,
      fontSize: type.body, // R01: tag and verdict pills at the 36 px phone size
      lineHeight: 1.2,
      fontWeight: 800,
      textTransform: "uppercase",
      letterSpacing: "0.04em",
      opacity,
      whiteSpace: "nowrap",
    }}
  >
    {text}
  </div>
);

const WorldPanel: React.FC<{
  panel: ComparePanel;
  w: number;
  h: number;
  nowMs: number;
  sharedWorld: World | null;
  sharedTimeline: ReturnType<typeof buildTimeline>;
  sceneId: string;
  sceneStartMs: number;
  turnEnds: Record<string, number>;
}> = ({ panel, w, h, nowMs, sharedWorld, sharedTimeline, sceneId, sceneStartMs, turnEnds: ends }) => {
  const isShared = panel.world === "shared";
  const world = isShared ? sharedWorld : (panel.world as World | undefined);
  if (!world) {
    throw new Error(
      `Compare panel "${panel.title}": kind "world" needs props.world (a local world) or "shared" with a top-level world in scenes.json.`,
    );
  }
  const timeline = useMemo(
    () => (isShared ? sharedTimeline : localTimeline(panel.steps ?? [], sceneId, sceneStartMs, ends)),
    [isShared, sharedTimeline, panel.steps, sceneId, sceneStartMs, ends],
  );
  const camera = useMemo(() => ({ ...fitCamera(world, w, h), ...(panel.camera ?? {}) }), [world, w, h, panel.camera]);
  const only = ringInsetFilter(world, viewScale(world, w, h, camera));
  return (
    <WorldCanvas world={world} timeline={timeline} nowMs={nowMs} width={w} height={h} camera={camera} idPrefix={sceneId} only={only} noteScene={isShared ? sceneId.replace(/-(left|right)$/, "") : sceneId} ringTextPx={PANEL_RING_TEXT_PX} />
  );
};

// Table: bands of cells (tableLayout.ts picks the band count with the largest text), each band
// repeating the row labels and its own column headers. W11b: a row whose cell count differs from the
// columns, or geometry that cannot keep text at 28 px, stops the render with the numbers (R01, R03).
const TablePanel: React.FC<{ panel: ComparePanel; rows: RowState[]; hasTitle: boolean; frame: number }> = ({ panel, rows, hasTitle, frame }) => {
  const problems = tableProblems(panel, hasTitle);
  if (problems.length) throw new Error(`Compare table "${panel.title}": ${problems.join("; ")}`);
  const cols = panel.columns ?? [];
  const L = panelTableLayout(panel, hasTitle);
  const { cell, cellW, rowH, labelW, font, labelFont } = L;
  const colorOf = (v: string) => panel.valueColors?.[v];
  // Fade in over `frames` from a finite cue frame; null (visible from the start) is fully shown.
  const fadeIn = (at: number | null, frames: number) => (at === null ? 1 : interpolate(frame, [at, at + frames], [0, 1], { ...clamp, easing: easeOut }));
  return (
    <div style={{ position: "absolute", left: TABLE_PAD_X, top: TABLE_PAD_TOP, right: TABLE_PAD_X, fontFamily: fonts.sans, display: "flex", flexDirection: "column", gap: L.bandGap }}>
      {L.bands.map((band, b) => (
        <div key={b}>
          {cols.length ? (
            <div style={{ display: "flex", alignItems: "center", height: rowH }}>
              <div style={{ width: labelW, flexShrink: 0 }} />
              {band.map((i) => (
                <div key={i} style={{ width: cellW, marginRight: TABLE_CELL_GAP, flexShrink: 0, textAlign: "center", fontFamily: fonts.mono, fontSize: font, fontWeight: 700, color: colors.muted }}>
                  {cols[i]}
                </div>
              ))}
            </div>
          ) : null}
          {rows.map((r) => {
            if (!r.visible) return <div key={r.id} style={{ height: rowH }} />;
            const rp = fadeIn(r.at, 10);
            return (
              <div key={r.id} style={{ display: "flex", alignItems: "center", height: rowH, opacity: rp }}>
                <div style={{ width: labelW, flexShrink: 0, fontSize: Math.max(type.min, Math.min(type.grid, labelFont)), fontWeight: 800, color: colors.text, whiteSpace: "nowrap" }}>{r.label}</div>
                {band.map((i) => {
                  const c = r.cells[i];
                  const shown = c.filled ? fadeIn(c.at, 8) : 0;
                  const text = shown > 0 ? c.text : "?";
                  const fill = shown > 0 ? colorOf(text) : undefined;
                  return (
                    <div
                      key={i}
                      style={{
                        width: cellW,
                        height: cell,
                        marginRight: TABLE_CELL_GAP,
                        flexShrink: 0,
                        borderRadius: 10,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        background: fill ?? colors.surfaceRaised,
                        color: fill ? colors.bg : shown > 0 ? colors.text : colors.muted,
                        fontFamily: fonts.mono,
                        fontSize: font,
                        fontWeight: 800,
                        outline: r.tinted.has(i) ? `6px solid ${tintColor(r.tinted.get(i)!)}` : r.marked.has(i) ? `4px dashed ${colors.text}` : "none",
                        outlineOffset: 3,
                      }}
                    >
                      {text}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
};

const TextPanel: React.FC<{ lines: { text: string; at: number | null; visible: boolean }[]; frame: number }> = ({ lines, frame }) => (
  <div style={{ position: "absolute", left: 24, top: 12, right: 24, display: "flex", flexDirection: "column", gap: 18, fontFamily: fonts.sans }}>
    {lines.map((l, i) => {
      const lp = l.at === null ? 1 : interpolate(frame, [l.at, l.at + 10], [0, 1], { ...clamp, easing: easeOut });
      return (
        <div key={i} style={{ fontSize: type.body + 4, fontWeight: 700, color: colors.text, lineHeight: 1.25, opacity: lp, translate: `0px ${(1 - lp) * 10}px` }}>
          {l.text}
        </div>
      );
    })}
  </div>
);
