import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { colors, fonts, radius, type } from "../theme";
import { answerFrame, clamp, easeOut } from "../time";
import type { SceneProps } from "../types";
import { Stage } from "./common";

export type CheckProps = {
  question: string;
  options?: string[]; // up to four; omit for an open question
  correct?: number; // 0-based index into options; needs answerAt
  answer?: string; // the spoken answer, shown on its cue; needs answerAt
  answerAtMs?: number;
};

// Two variants (references/learning-design.md J10):
// - answered retrieval card: `answer` and/or `correct` with `answerAt`. A thinking bar runs from
//   the card's entrance to the answer cue; the answer appears ON its word (zero lead), never before.
// - final self-test card: no answer and no correct option. Nothing is revealed; a footer tells the
//   learner to answer aloud. The answer lives in learn/selftest.md, not on screen.
// An answer without a cue is never shown: there is no time-based default (build_manifest.py errors).
export const CheckYourselfCard: React.FC<SceneProps<CheckProps>> = ({
  question,
  options = [],
  correct,
  answer,
  answerAtMs,
  fromFrame,
  enter,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const answered = answer !== undefined || correct !== undefined;
  const aStart = answered ? answerFrame(answerAtMs, fromFrame, fps) : null;
  const a = aStart === null ? 0 : interpolate(frame, [aStart, aStart + 12], [0, 1], { ...clamp, easing: easeOut });
  const think = aStart === null ? 0 : interpolate(frame, [12, Math.max(13, aStart)], [0, 1], clamp);
  const showRight = (i: number) => correct === i && a > 0.5;

  return (
    <Stage enter={enter} heading={answered ? "Check yourself" : "Your turn: answer aloud"}>
      <div style={{ fontFamily: fonts.sans, display: "flex", flexDirection: "column", gap: 24 }}>
        <div style={{ fontSize: type.heading - 8, fontWeight: 700, color: colors.text, lineHeight: 1.2 }}>{question}</div>
        {aStart !== null ? (
          <div style={{ height: 8, borderRadius: 4, background: colors.surface, overflow: "hidden" }}>
            <div style={{ width: `${think * 100}%`, height: "100%", background: colors.warn, opacity: 1 - a }} />
          </div>
        ) : null}
        {options.slice(0, 4).map((o, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 22,
              padding: "16px 26px",
              borderRadius: radius.card,
              background: colors.surface,
              border: `3px solid ${showRight(i) ? colors.good : colors.line}`,
              fontSize: type.body,
              fontWeight: 600,
              color: colors.text,
              opacity: correct !== undefined && correct !== i ? 1 - 0.45 * a : 1,
            }}
          >
            <span style={{ fontWeight: 800, color: showRight(i) ? colors.good : colors.accent }}>
              {String.fromCharCode(65 + i)}
            </span>
            {o}
          </div>
        ))}
        {answer && a > 0 ? (
          <div
            style={{
              marginTop: 8,
              padding: "18px 28px",
              borderRadius: radius.card,
              background: colors.surfaceRaised,
              borderLeft: `8px solid ${colors.good}`,
              fontSize: type.body,
              fontWeight: 700,
              color: colors.text,
              opacity: a,
              translate: `0px ${(1 - a) * 20}px`,
            }}
          >
            {answer}
          </div>
        ) : null}
        {!answered ? (
          <div style={{ marginTop: 12, fontSize: type.label, fontWeight: 600, color: colors.muted }}>
            Pause the video and say your answer before you check learn/.
          </div>
        ) : null}
      </div>
    </Stage>
  );
};
