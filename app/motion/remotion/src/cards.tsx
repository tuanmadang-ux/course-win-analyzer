/**
 * Các thẻ B-roll bản Remotion. Nhận đúng bộ trường như bản HyperFrames
 * (xem app/motion/cards.py) để hai engine thay thế được cho nhau.
 */

import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { color, font, panel, zone } from "./theme";

/** Hiệu ứng vào dùng chung: trượt lên + hiện dần, có độ nảy nhẹ. */
const useEnter = (delay = 0) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: frame - delay, fps, config: { damping: 200 }, durationInFrames: 18 });
  return {
    opacity: interpolate(s, [0, 1], [0, 1]),
    transform: `translateY(${interpolate(s, [0, 1], [70, 0])}px)`,
  };
};

const Shell: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  // Nền phải trong suốt — thẻ chồng lên video, không thay thế nó
  <AbsoluteFill style={{ fontFamily: font, backgroundColor: "transparent" }}>
    <div style={zone}>
      <div style={panel}>{children}</div>
    </div>
  </AbsoluteFill>
);

// --- stat -------------------------------------------------------------------

export const Stat: React.FC<{ value?: string; label?: string; note?: string }> = ({
  value = "70%",
  label = "",
  note = "",
}) => {
  const enter = useEnter();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = spring({ frame: frame - 4, fps, config: { damping: 12 }, durationInFrames: 16 });

  return (
    <AbsoluteFill style={{ fontFamily: font, backgroundColor: "transparent" }}>
      <div style={zone}>
        <div style={{ ...panel, ...enter }}>
          <div
            style={{
              fontSize: 168,
              fontWeight: 800,
              lineHeight: 0.98,
              letterSpacing: -3,
              color: color.accent,
              transform: `scale(${interpolate(pop, [0, 1], [0.55, 1])})`,
              transformOrigin: "left center",
            }}
          >
            {value}
          </div>
          {label ? (
            <div style={{ fontSize: 48, fontWeight: 600, color: color.ink, marginTop: 16 }}>
              {label}
            </div>
          ) : null}
          {note ? (
            <div style={{ fontSize: 36, color: color.inkDim, marginTop: 14 }}>{note}</div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// --- steps ------------------------------------------------------------------

export const Steps: React.FC<{ title?: string; items?: string; ordered?: boolean }> = ({
  title = "",
  items = "",
  ordered = true,
}) => {
  const enter = useEnter();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Chuỗi ngăn bởi "|" — cùng quy ước với bản HyperFrames
  const list = String(items).split("|").map((s) => s.trim()).filter(Boolean).slice(0, 5);

  return (
    <AbsoluteFill style={{ fontFamily: font, backgroundColor: "transparent" }}>
      <div style={zone}>
        <div style={{ ...panel, ...enter }}>
          {title ? (
            <div style={{ fontSize: 46, fontWeight: 800, color: color.accent, marginBottom: 30 }}>
              {title}
            </div>
          ) : null}
          {list.map((text, i) => {
            // Các ý hiện lần lượt để mắt bám theo từng dòng
            const s = spring({
              frame: frame - 10 - i * 7,
              fps,
              config: { damping: 200 },
              durationInFrames: 14,
            });
            return (
              <div
                key={i}
                style={{
                  display: "flex",
                  gap: 26,
                  alignItems: "flex-start",
                  marginTop: i === 0 ? 0 : 26,
                  opacity: s,
                  transform: `translateX(${interpolate(s, [0, 1], [-40, 0])}px)`,
                }}
              >
                <div
                  style={{
                    width: 62, height: 62, flexShrink: 0, borderRadius: "50%",
                    background: color.accent, color: "#06121f",
                    fontSize: 34, fontWeight: 800,
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}
                >
                  {ordered ? i + 1 : "•"}
                </div>
                <div style={{ fontSize: 44, fontWeight: 600, lineHeight: 1.28, color: color.ink, paddingTop: 4 }}>
                  {text}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// --- quote ------------------------------------------------------------------

export const Quote: React.FC<{ text?: string; who?: string }> = ({ text = "", who = "" }) => {
  const enter = useEnter();
  return (
    <Shell>
      <div style={{ display: "flex", gap: 34, ...enter }}>
        <div
          style={{
            width: 12, borderRadius: 99, flexShrink: 0,
            background: `linear-gradient(180deg, ${color.accent}, ${color.accent2})`,
          }}
        />
        <div>
          <div style={{ fontSize: 60, fontWeight: 700, lineHeight: 1.25, color: color.ink }}>
            {text}
          </div>
          {who ? (
            <div style={{ fontSize: 36, color: color.inkDim, marginTop: 22, fontWeight: 500 }}>
              {who}
            </div>
          ) : null}
        </div>
      </div>
    </Shell>
  );
};

// --- compare ----------------------------------------------------------------

const Col: React.FC<{ cap: string; text: string; good: boolean; delay: number }> = ({
  cap, text, good, delay,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: frame - delay, fps, config: { damping: 200 }, durationInFrames: 14 });
  return (
    <div
      style={{
        flex: 1, borderRadius: 26, padding: "34px 30px",
        background: good ? "rgba(53,201,139,0.16)" : "rgba(242,85,90,0.16)",
        border: `2px solid ${good ? "rgba(53,201,139,0.5)" : "rgba(242,85,90,0.5)"}`,
        opacity: s,
        transform: `translateX(${interpolate(s, [0, 1], [good ? 50 : -50, 0])}px)`,
      }}
    >
      <div
        style={{
          fontSize: 32, fontWeight: 800, letterSpacing: 1, textTransform: "uppercase",
          marginBottom: 16, color: good ? color.good : color.bad,
        }}
      >
        {cap}
      </div>
      <div style={{ fontSize: 40, fontWeight: 600, lineHeight: 1.28, color: color.ink }}>{text}</div>
    </div>
  );
};

export const Compare: React.FC<{
  bad_label?: string; bad_text?: string; good_label?: string; good_text?: string;
}> = ({ bad_label = "Sai", bad_text = "", good_label = "Đúng", good_text = "" }) => {
  const enter = useEnter();
  return (
    <Shell>
      <div style={{ display: "flex", gap: 22, ...enter }}>
        <Col cap={bad_label} text={bad_text} good={false} delay={7} />
        <div style={{ fontSize: 34, fontWeight: 800, color: color.inkDim, alignSelf: "center", width: 56, textAlign: "center" }}>
          VS
        </div>
        <Col cap={good_label} text={good_text} good delay={11} />
      </div>
    </Shell>
  );
};

// --- hook -------------------------------------------------------------------

export const Hook: React.FC<{ text?: string; kicker?: string }> = ({ text = "", kicker = "" }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 16 });
  const rule = spring({ frame: frame - 10, fps, config: { damping: 200 }, durationInFrames: 14 });

  // Cụm bọc trong *sao* được tô màu nhấn — cùng quy ước với bản HyperFrames
  const parts = String(text).split(/\*(.+?)\*/);

  return (
    <AbsoluteFill style={{ fontFamily: font, backgroundColor: "transparent" }}>
      <div
        style={{
          // Neo cùng vùng an toàn với các thẻ khác: mặt người nói nằm quanh
          // y=400..900, đặt chữ ở đó là đè thẳng lên mặt.
          position: "absolute", left: 80, right: 80, bottom: 470,
          opacity: s,
          transform: `translateY(${interpolate(s, [0, 1], [40, 0])}px)`,
          textShadow: "0 4px 18px rgba(0,0,0,0.85), 0 0 3px rgba(0,0,0,0.9)",
        }}
      >
        {kicker ? (
          <div
            style={{
              fontSize: 38, fontWeight: 700, letterSpacing: 3, textTransform: "uppercase",
              color: color.accent, marginBottom: 24,
            }}
          >
            {kicker}
          </div>
        ) : null}
        <div style={{ fontSize: 104, fontWeight: 900, lineHeight: 1.08, letterSpacing: -2, color: color.ink }}>
          {parts.map((part, i) =>
            i % 2 ? (
              <span key={i} style={{ color: color.accent2 }}>{part}</span>
            ) : (
              <React.Fragment key={i}>{part}</React.Fragment>
            )
          )}
        </div>
        <div
          style={{
            height: 8, width: 160, borderRadius: 99, background: color.accent, marginTop: 34,
            transform: `scaleX(${rule})`, transformOrigin: "left",
          }}
        />
      </div>
    </AbsoluteFill>
  );
};

// --- lower_third ------------------------------------------------------------

export const LowerThird: React.FC<{ name?: string; role?: string }> = ({ name = "", role = "" }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 15 });

  return (
    <AbsoluteFill style={{ fontFamily: font, backgroundColor: "transparent" }}>
      <div
        style={{
          position: "absolute", left: 72, bottom: 470,
          opacity: s,
          transform: `translateX(${interpolate(s, [0, 1], [-120, 0])}px)`,
        }}
      >
        <div
          style={{
            display: "inline-block", padding: "26px 40px",
            background: color.panel, borderLeft: `10px solid ${color.accent}`,
            borderRadius: "0 22px 22px 0", boxShadow: "0 24px 70px rgba(0,0,0,0.55)",
          }}
        >
          <div style={{ fontSize: 56, fontWeight: 800, color: color.ink }}>{name}</div>
          {role ? (
            <div style={{ fontSize: 34, fontWeight: 500, color: color.inkDim, marginTop: 8 }}>
              {role}
            </div>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};
