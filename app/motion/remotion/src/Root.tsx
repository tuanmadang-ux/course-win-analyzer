/**
 * Khai báo composition. Mỗi id ở đây phải trùng tên loại thẻ trong
 * app/motion/cards.py — Python gọi `remotion render src/index.ts <id>`.
 */

import React from "react";
import { Composition } from "remotion";
import { Compare, Hook, LowerThird, Quote, Stat, Steps } from "./cards";
import { CARD_FRAMES, FPS, HEIGHT, WIDTH } from "./theme";

const base = {
  durationInFrames: CARD_FRAMES,
  fps: FPS,
  width: WIDTH,
  height: HEIGHT,
} as const;

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="stat"
      component={Stat}
      {...base}
      defaultProps={{ value: "70%", label: "nhãn của con số", note: "" }}
    />
    <Composition
      id="steps"
      component={Steps}
      {...base}
      defaultProps={{ title: "", items: "Ý một|Ý hai|Ý ba", ordered: true }}
    />
    <Composition
      id="quote"
      component={Quote}
      {...base}
      defaultProps={{ text: "Câu trích dẫn", who: "" }}
    />
    <Composition
      id="compare"
      component={Compare}
      {...base}
      defaultProps={{
        bad_label: "Sai",
        bad_text: "Cách làm cũ",
        good_label: "Đúng",
        good_text: "Cách làm mới",
      }}
    />
    <Composition
      id="hook"
      component={Hook}
      {...base}
      defaultProps={{ text: "Câu móc mở đầu", kicker: "" }}
    />
    <Composition
      id="lower-third"
      component={LowerThird}
      {...base}
      defaultProps={{ name: "Tên của bạn", role: "" }}
    />
  </>
);
