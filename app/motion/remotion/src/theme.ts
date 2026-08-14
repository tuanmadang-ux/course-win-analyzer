/**
 * Cùng bảng màu và cùng vùng an toàn với bộ template HyperFrames, để hai engine
 * cho ra thẻ nhìn giống nhau — đổi engine không được làm đổi diện mạo video.
 */

export const WIDTH = 1080;
export const HEIGHT = 1920;
export const FPS = 30;
export const CARD_FRAMES = 90; // 3 giây, khớp CARD_SECONDS bên Python

export const color = {
  accent: "#4f9cf9",
  accent2: "#ffd166",
  ink: "#f2f6fb",
  inkDim: "#aab6c6",
  panel: "rgba(14, 17, 22, 0.92)",
  line: "rgba(79, 156, 249, 0.55)",
  bad: "#ff8b8f",
  good: "#6ee7b0",
} as const;

export const font =
  '"Be Vietnam Pro", "Inter", "Segoe UI", system-ui, sans-serif';

/**
 * Vùng giữa khung: dưới mặt người nói, trên phụ đề.
 *
 * Neo theo mép DƯỚI — thẻ nhiều mục mọc ngược lên vùng trống thay vì thò xuống
 * đè lên phụ đề. Phải khớp `.zone` trong project/assets/theme.css, nếu không
 * đổi engine sẽ làm thẻ nhảy vị trí.
 */
export const zone: React.CSSProperties = {
  position: "absolute",
  left: 72,
  right: 72,
  bottom: 470,
};

export const panel: React.CSSProperties = {
  background: color.panel,
  border: `3px solid ${color.line}`,
  borderRadius: 40,
  padding: "54px 58px",
  boxShadow: "0 24px 70px rgba(0,0,0,0.55)",
};
