"""Bộ lệnh của bot: dán bài → đào insight → viết → duyệt → lên lịch, ngay trên điện thoại.

Thiết kế xoay quanh một chuyện: trên điện thoại, gõ lệnh thì phiền, dán thì dễ.
Nên bot đoán ý — bạn cứ dán, tin đầu tiên là bài gốc, các tin sau là bình luận.
Lệnh chỉ dùng khi muốn nói rõ.

Mọi việc nặng (đào, viết) đều gọi thẳng vào cùng module mà web app dùng, và ghi
vào cùng một file SQLite. Mở web lên là thấy y hệt.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from radar import create, ingest, mine, publish, store
from radar.bot.tg import Telegram, esc, keyboard
from radar.config import (
    FORMAT_LABELS,
    MineSettings,
    WriteSettings,
    has_apify,
    has_claude,
    has_page,
)
from radar.create.originality import full_text
from radar.measure import report as build_report
from radar.mine.insight import KIND_LABELS
from radar.publish import schedule as scheduler
from radar.service import recheck_draft

log = logging.getLogger(__name__)

FIELD_LABELS = {"hook": "hook", "body": "thân bài", "cta": "CTA"}

MENU = [
    ("bai", "Dán bài gốc của đối thủ"),
    ("bl", "Dán phần bình luận"),
    ("dao", "Đào insight từ những gì vừa dán"),
    ("insight", "Xem insight đang chờ"),
    ("nhap", "Bài nháp chờ duyệt"),
    ("lich", "Lịch đăng + khung giờ vàng"),
    ("baocao", "Công thức nào đang ăn"),
    ("nguon", "Chọn / xem nguồn theo dõi"),
    ("huy", "Xoá phần đang dán dở"),
    ("trogiup", "Hướng dẫn"),
]

HELP = """<b>📡 Radar đối thủ — ra lệnh từ đây</b>

Cách nhanh nhất: <b>cứ dán, không cần lệnh</b>.
Tin đầu tiên = bài gốc của đối thủ. Các tin sau = bình luận (dán bao nhiêu lần cũng được).
Dán xong bấm /dao.

<b>Lệnh khi cần nói rõ</b>
/bai — tin tiếp theo là bài gốc
/bl — tin tiếp theo là bình luận
/dao — đào insight từ những gì vừa dán
/insight — xem lại insight đang chờ
/nhap — bài nháp chờ bạn duyệt
/lich — lịch đăng + khung giờ vàng
/baocao — công thức nào đang cho tương tác cao nhất
/nguon — chọn nguồn đang làm việc
/themnguon Tên | link — thêm đối thủ mới
/huy — xoá phần đang dán dở
/trangthai — kiểm tra key và kết nối

<b>Ba điều bot sẽ không làm</b>
· Không đăng gì khi bạn chưa bấm Duyệt.
· Không cho duyệt bài còn trùng lặp với bài gốc.
· Không lưu tên người bình luận."""


@dataclass
class ChatState:
    source_id: str = ""
    mode: str = ""                      # "" | "post" | "comments"
    post_text: str = ""
    comments_text: str = ""
    url: str = ""
    last_post_id: str = ""
    edit_draft: str = ""                # đang chờ nội dung mới cho bài nháp nào
    edit_field: str = ""                # "hook" | "body" | "cta"
    updated_at: float = field(default_factory=time.time)

    def clear_buffer(self) -> None:
        self.mode = ""
        self.post_text = ""
        self.comments_text = ""
        self.url = ""

    def clear_edit(self) -> None:
        self.edit_draft = ""
        self.edit_field = ""


class Handlers:
    """Giữ trạng thái hội thoại theo từng chat và xử lý lệnh."""

    def __init__(self, bot: Telegram) -> None:
        self.bot = bot
        self._states: dict[int, ChatState] = {}
        self._lock = threading.Lock()

    def state(self, chat_id: int) -> ChatState:
        with self._lock:
            st = self._states.setdefault(chat_id, ChatState())
            st.updated_at = time.time()
        return st

    # -- tiện ích ----------------------------------------------------------

    def say(self, chat_id: int, text: str, buttons: dict | None = None) -> int | None:
        return self.bot.send(chat_id, text, buttons)

    def _current_source(self, chat_id: int) -> dict | None:
        st = self.state(chat_id)
        if st.source_id:
            source = store.get_source(st.source_id)
            if source:
                return source
        sources = store.list_sources()
        if len(sources) == 1:
            st.source_id = sources[0]["id"]
            return sources[0]
        return None

    # ==================================================================
    # Lệnh
    # ==================================================================

    def cmd_start(self, chat_id: int, _args: str) -> None:
        self.say(chat_id, HELP)
        if not store.list_sources():
            self.say(chat_id, "Chưa có nguồn nào. Thêm đối thủ đầu tiên:\n"
                              "<code>/themnguon Trung tâm ABC | https://facebook.com/abc</code>")

    def cmd_status(self, chat_id: int, _args: str) -> None:
        sources = store.list_sources()
        drafts = store.list_drafts()
        pending = sum(1 for d in drafts if d["status"] == "draft")
        insights = len(store.list_insights(status="new"))

        def mark(on: bool) -> str:
            return "✅" if on else "⬜"

        self.say(chat_id, (
            "<b>Trạng thái</b>\n"
            f"{mark(has_claude())} Claude — đào insight &amp; viết bài\n"
            f"{mark(has_apify())} Apify — quét tự động\n"
            f"{mark(has_page())} Fanpage — đăng &amp; đọc chỉ số\n\n"
            f"📚 {len(sources)} nguồn · {len(store.list_posts(limit=999))} bài đã thu\n"
            f"💡 {insights} insight đang chờ\n"
            f"📝 {pending} bài nháp chờ duyệt"
        ))

    def cmd_sources(self, chat_id: int, _args: str) -> None:
        sources = store.list_sources()
        if not sources:
            self.say(chat_id, "Chưa có nguồn nào.\n"
                              "<code>/themnguon Trung tâm ABC | https://facebook.com/abc</code>")
            return
        current = self.state(chat_id).source_id
        rows = [[(f"{'▶ ' if s['id'] == current else ''}{s['name']} ({s['post_count']} bài)",
                  f"src:{s['id']}")] for s in sources[:20]]
        self.say(chat_id, "Chọn nguồn đang làm việc:", keyboard(rows))

    def cmd_add_source(self, chat_id: int, args: str) -> None:
        if not args.strip():
            self.say(chat_id, "Cú pháp: <code>/themnguon Tên đối thủ | link fanpage</code>")
            return
        name, _, ref = args.partition("|")
        source = store.add_source(name.strip(), ref.strip())
        self.state(chat_id).source_id = source["id"]
        self.say(chat_id, f"✅ Đã thêm <b>{esc(source['name'])}</b> và chọn làm nguồn hiện tại.\n"
                          f"Giờ dán bài gốc của họ vào đây.")

    def cmd_post(self, chat_id: int, args: str) -> None:
        st = self.state(chat_id)
        if args.strip():
            st.post_text = args.strip()
            st.mode = "comments"
            self.say(chat_id, f"📄 Đã nhận bài gốc ({len(st.post_text)} ký tự).\n"
                              f"Giờ dán phần bình luận.")
            return
        st.mode = "post"
        self.say(chat_id, "📄 Gửi nội dung bài gốc của đối thủ (dán nguyên văn).")

    def cmd_comments(self, chat_id: int, args: str) -> None:
        st = self.state(chat_id)
        st.mode = "comments"
        if args.strip():
            self._add_comments(chat_id, args.strip())
            return
        self.say(chat_id, "💬 Dán phần bình luận. Dài quá thì chia làm nhiều tin, "
                          "bot cộng dồn. Xong bấm /dao.")

    def _add_comments(self, chat_id: int, text: str) -> None:
        st = self.state(chat_id)
        st.comments_text = f"{st.comments_text}\n\n{text}" if st.comments_text else text
        from radar.ingest.paste import parse_comments

        count = len(parse_comments(st.comments_text))
        self.say(chat_id, f"💬 Đã nhận, tổng cộng tách được <b>{count}</b> bình luận.\n"
                          f"Dán tiếp, hoặc bấm /dao để đào insight.",
                 keyboard([[("🔎 Đào insight ngay", "act:dao")]]))

    def cmd_cancel(self, chat_id: int, _args: str) -> None:
        st = self.state(chat_id)
        st.clear_buffer()
        st.clear_edit()
        self.say(chat_id, "🗑 Đã xoá phần đang dán dở.")

    # -- đào ---------------------------------------------------------------

    def cmd_mine(self, chat_id: int, _args: str) -> None:
        st = self.state(chat_id)
        if not st.post_text.strip():
            self.say(chat_id, "Chưa có bài gốc nào. Dán bài của đối thủ vào trước đã.")
            return

        source = self._current_source(chat_id)
        if not source:
            self.say(chat_id, "Chưa chọn nguồn. Bấm /nguon để chọn, "
                              "hoặc <code>/themnguon Tên | link</code>.")
            return

        self.say(chat_id, f"🔎 Đang đọc bình luận… ({esc(source['name'])})")
        result = ingest.collect_from_paste(
            source["id"], st.post_text, st.comments_text, st.url
        )
        post_id = result["post_ids"][0]
        mined = mine.mine_post(post_id, MineSettings())
        st.last_post_id = post_id
        st.clear_buffer()

        if mined.get("error"):
            self.say(chat_id, f"⚠️ {esc(mined['error'])}")
            return

        insights = mined.get("insights", [])
        self.say(chat_id, (
            f"✅ Xong: <b>{mined['comments']}</b> bình luận → giữ <b>{mined['kept']}</b> "
            f"cái đáng đọc → <b>{len(insights)}</b> insight."
        ))
        self._show_insights(chat_id, insights)

    def cmd_insights(self, chat_id: int, _args: str) -> None:
        insights = store.list_insights(status="new")
        if not insights:
            self.say(chat_id, "Chưa có insight nào đang chờ. Dán một bài nhiều bình luận vào đi.")
            return
        self._show_insights(chat_id, insights[:8])

    def _show_insights(self, chat_id: int, insights: list[dict]) -> None:
        if not insights:
            return
        for ins in insights[:8]:
            quotes = "\n".join(f"· <i>{esc(q[:180])}</i>" for q in (ins.get("quotes") or [])[:2])
            gap = f"\n\n<b>Bài gốc còn thiếu:</b> {esc(ins['gap'])}" if ins.get("gap") else ""
            body = (
                f"💡 <b>{esc(ins['title'])}</b>\n"
                f"<i>{esc(KIND_LABELS.get(ins['kind'], ins['kind']))} · "
                f"{ins['size']} người cùng nói</i>\n\n"
                f"{esc(ins.get('detail', ''))}{gap}\n\n{quotes}"
            )
            self.say(chat_id, body, keyboard([[
                ("✍️ Viết bài", f"w:post:{ins['id']}"),
                ("🎬 Kịch bản Reels", f"w:reels:{ins['id']}"),
            ], [
                ("🙈 Bỏ qua", f"iskip:{ins['id']}"),
            ]]))

    # -- viết --------------------------------------------------------------

    def write_from_insight(self, chat_id: int, insight_id: str, fmt: str) -> None:
        insight = store.get_insight(insight_id)
        if not insight:
            self.say(chat_id, "Không tìm thấy insight này nữa.")
            return

        label = FORMAT_LABELS.get(fmt, fmt)
        self.say(chat_id, f"✍️ Đang viết <b>{esc(label)}</b>… "
                          f"{'(vài giây)' if has_claude() else '(chưa có key Claude — sẽ ra dàn ý)'}")
        result = create.drafts_for_insights([insight_id], WriteSettings(formats=(fmt,)))
        for draft in result["drafts"]:
            self.show_draft(chat_id, draft)

    # -- bài nháp ----------------------------------------------------------

    def cmd_drafts(self, chat_id: int, args: str) -> None:
        wanted = (args or "").strip().lower()
        status = wanted if wanted in ("draft", "approved", "scheduled", "published") else "draft"
        drafts = store.list_drafts(status)
        if not drafts:
            self.say(chat_id, f"Không có bài nào ở trạng thái “{status}”.")
            return
        self.say(chat_id, f"📝 {len(drafts)} bài — hiện {min(len(drafts), 5)} cái mới nhất:")
        for draft in drafts[:5]:
            self.show_draft(chat_id, draft)

    def show_draft(self, chat_id: int, draft: dict, message_id: int | None = None) -> None:
        text = self._draft_text(draft)
        buttons = self._draft_buttons(draft)
        if message_id:
            self.bot.edit(chat_id, message_id, text, buttons)
        else:
            self.say(chat_id, text, buttons)

    def _draft_text(self, draft: dict) -> str:
        status_label = {
            "draft": "⏳ Chờ duyệt", "approved": "✅ Đã duyệt",
            "scheduled": "🗓 Đã lên lịch", "published": "📢 Đã đăng",
            "rejected": "🚫 Đã bỏ",
        }.get(draft["status"], draft["status"])

        head = (f"{status_label} · {esc(FORMAT_LABELS.get(draft['format'], draft['format']))} · "
                f"trùng {round(draft.get('similarity', 0) * 100)}%")
        if draft.get("scheduled_at"):
            head += f"\n🗓 {esc(scheduler.describe(draft['scheduled_at']))}"

        warnings = ""
        if draft.get("warnings"):
            warnings = "\n\n⚠️ <b>" + "\n".join(esc(w) for w in draft["warnings"]) + "</b>"

        alt_hooks = ""
        hooks = draft.get("hooks") or []
        if len(hooks) > 1:
            alt_hooks = "\n\n<i>Hook khác:</i>\n" + "\n".join(
                f"{i + 1}. {esc(h)}" for i, h in enumerate(hooks[1:], start=1)
            )

        return (
            f"{head}{warnings}\n\n"
            f"<b>{esc(draft.get('hook', ''))}</b>\n\n"
            f"{esc(draft.get('body', ''))}\n\n"
            f"<i>{esc(draft.get('cta', ''))}</i>{alt_hooks}"
        )

    def _draft_buttons(self, draft: dict) -> dict:
        did = draft["id"]
        rows: list[list[tuple[str, str]]] = []

        if draft["status"] == "draft" and not draft.get("warnings"):
            rows.append([("✅ Duyệt", f"d:ok:{did}"), ("🚫 Bỏ", f"d:no:{did}")])
        elif draft["status"] == "draft":
            rows.append([("🚫 Bỏ", f"d:no:{did}")])

        if draft["status"] == "approved":
            row = [("🗓 Lên lịch giờ vàng", f"d:plan:{did}")]
            if has_page():
                row.append(("📢 Đăng ngay", f"d:now:{did}"))
            rows.append(row)

        if draft["status"] in ("draft", "approved"):
            rows.append([("✏️ Sửa hook", f"d:ehook:{did}"),
                         ("✏️ Sửa thân bài", f"d:ebody:{did}")])

        hooks = draft.get("hooks") or []
        if len(hooks) > 1 and draft["status"] in ("draft", "approved"):
            rows.append([(f"🔁 Dùng hook {i + 1}", f"d:hook{i}:{did}")
                         for i in range(1, min(len(hooks), 3))])

        rows.append([("🗑 Xoá", f"d:del:{did}")])
        return keyboard(rows)

    # -- lịch & báo cáo ----------------------------------------------------

    def cmd_schedule(self, chat_id: int, _args: str) -> None:
        info = scheduler.golden_hours()
        top = ", ".join(f"{h}h" for h, _ in
                        sorted(info["hours"].items(), key=lambda kv: -kv[1])[:4])
        source = ("tính từ chính trang của bạn" if info["source"] == "page"
                  else "mốc phổ biến ở VN — trang chưa đủ bài để tính riêng")

        lines = [f"🕐 <b>Khung giờ vàng</b> ({source}): {esc(top)}"]

        upcoming = [d for d in store.list_drafts("scheduled") if d.get("scheduled_at")]
        upcoming.sort(key=lambda d: d["scheduled_at"])
        if upcoming:
            lines.append("\n<b>Sắp đăng</b>")
            for d in upcoming[:8]:
                mark = "📤 tự đăng" if d.get("published_id") else "✋ bạn đăng tay"
                lines.append(f"· {esc(scheduler.describe(d['scheduled_at']))} — "
                             f"{esc((d.get('hook') or '')[:70])} <i>({mark})</i>")
        else:
            lines.append("\nChưa có bài nào lên lịch.")

        due = publish.due_now()
        if due:
            lines.append(f"\n⏰ <b>{len(due)} bài đã tới giờ mà chưa đăng</b> — bấm /nhap scheduled.")

        self.say(chat_id, "\n".join(lines))

    def cmd_report(self, chat_id: int, _args: str) -> None:
        rep = build_report()
        if not rep["posts"]:
            self.say(chat_id, "Chưa có bài nào đăng qua hệ thống nên chưa đo được gì.")
            return

        lines = [f"📊 <b>{rep['posts']} bài có số liệu</b>"]
        if rep["verdict"]:
            lines.append(f"\n{esc(rep['verdict'])}")
        for title, rows in (("Theo dạng insight", rep["by_kind"]),
                            ("Theo định dạng", rep["by_format"])):
            if not rows:
                continue
            lines.append(f"\n<b>{title}</b>")
            for g in rows[:5]:
                lines.append(f"· {esc(g['label'])} — {g['avg_engagement_rate'] * 100:.1f}% "
                             f"({g['posts']} bài)")
        self.say(chat_id, "\n".join(lines))

    # ==================================================================
    # Tin nhắn thường (không phải lệnh)
    # ==================================================================

    def on_text(self, chat_id: int, text: str) -> None:
        st = self.state(chat_id)

        # Đang sửa một bài nháp thì tin này là nội dung mới, không phải bài đối thủ
        if st.edit_draft:
            self._apply_edit(chat_id, text)
            return

        if st.mode == "post" or (not st.mode and not st.post_text):
            st.post_text = text
            st.mode = "comments"
            if text.startswith("http"):
                st.url = text.split()[0]
            self.say(chat_id, (
                f"📄 Đã nhận bài gốc ({len(text)} ký tự).\n"
                f"Giờ dán phần bình luận — dán nhiều tin cũng được."
            ))
            return

        self._add_comments(chat_id, text)

    def _apply_edit(self, chat_id: int, text: str) -> None:
        """Nhận nội dung sửa tay rồi đo lại độ trùng lặp ngay."""
        st = self.state(chat_id)
        draft_id, field_name = st.edit_draft, st.edit_field
        st.clear_edit()

        if not store.get_draft(draft_id):
            self.say(chat_id, "Bài này không còn nữa.")
            return

        store.update_draft(draft_id, **{field_name: text.strip()})
        # Sửa xong thì bài phải quay lại hàng chờ duyệt — người duyệt đọc lại từ đầu
        store.update_draft(draft_id, status="draft")
        draft = recheck_draft(draft_id) or store.get_draft(draft_id)

        label = FIELD_LABELS[field_name]
        note = ("⚠️ Vẫn còn cảnh báo." if draft.get("warnings")
                else "✅ Không còn cảnh báo, duyệt được rồi.")
        self.say(chat_id, f"✏️ Đã thay {label}. {note}")
        self.show_draft(chat_id, draft)

    # ==================================================================
    # Nút bấm
    # ==================================================================

    def on_callback(self, chat_id: int, message_id: int, data: str, callback_id: str) -> None:
        answer = ""

        if data.startswith("src:"):
            source = store.get_source(data[4:])
            if source:
                self.state(chat_id).source_id = source["id"]
                answer = f"Đang làm việc với {source['name']}"
                self.say(chat_id, f"▶ Nguồn hiện tại: <b>{esc(source['name'])}</b>")

        elif data == "act:dao":
            self.bot.answer(callback_id, "Đang đào…")
            self.cmd_mine(chat_id, "")
            return

        elif data.startswith("iskip:"):
            store.set_insight_status(data[6:], "ignored")
            self.bot.edit(chat_id, message_id, "🙈 <i>Đã bỏ qua insight này.</i>", keyboard([]))
            self.bot.answer(callback_id, "Đã bỏ qua")
            return

        elif data.startswith("w:"):
            _, fmt, insight_id = data.split(":", 2)
            self.bot.answer(callback_id, "Đang viết…")
            self.write_from_insight(chat_id, insight_id, fmt)
            return

        elif data.startswith("d:"):
            self._draft_action(chat_id, message_id, data, callback_id)
            return

        self.bot.answer(callback_id, answer)

    def _draft_action(self, chat_id: int, message_id: int, data: str, callback_id: str) -> None:
        _, action, draft_id = data.split(":", 2)
        draft = store.get_draft(draft_id)
        if not draft:
            self.bot.answer(callback_id, "Bài này không còn nữa")
            return

        if action in ("ehook", "ebody", "ecta"):
            field_name = {"ehook": "hook", "ebody": "body", "ecta": "cta"}[action]
            st = self.state(chat_id)
            st.edit_draft, st.edit_field = draft_id, field_name
            st.clear_buffer()
            self.bot.answer(callback_id, "Gửi nội dung mới")
            current = draft.get(field_name) or "(đang trống)"
            self.say(chat_id, (
                f"✏️ Gửi <b>{esc(FIELD_LABELS[field_name])}</b> mới cho bài này. "
                f"Tin nhắn tiếp theo sẽ thay thế toàn bộ phần đó.\n\n"
                f"<i>Đang là:</i>\n{esc(current[:600])}\n\n"
                f"Đổi ý thì bấm /huy."
            ))
            return

        try:
            if action == "ok":
                draft = publish.approve(draft_id)
                self.bot.answer(callback_id, "Đã duyệt")

            elif action == "no":
                draft = publish.reject(draft_id)
                self.bot.answer(callback_id, "Đã bỏ")

            elif action == "plan":
                result = publish.plan(draft_id)
                self.bot.answer(callback_id, "Đã lên lịch")
                note = ("Đã hẹn giờ trên Facebook" if result.get("on_facebook")
                        else "Ghi lịch nội bộ — tới giờ bạn đăng tay")
                self.say(chat_id, f"🗓 {esc(result['slot_label'])} — {note}.")
                draft = store.get_draft(draft_id)

            elif action == "now":
                draft = publish.publish_now(draft_id)
                self.bot.answer(callback_id, "Đã đăng")

            elif action == "del":
                store.delete_draft(draft_id)
                self.bot.edit(chat_id, message_id, "🗑 <i>Đã xoá bài nháp.</i>", keyboard([]))
                self.bot.answer(callback_id, "Đã xoá")
                return

            elif action.startswith("hook"):
                index = int(action[4:])
                hooks = draft.get("hooks") or []
                if 0 <= index < len(hooks):
                    store.update_draft(draft_id, hook=hooks[index])
                    draft = recheck_draft(draft_id) or store.get_draft(draft_id)
                self.bot.answer(callback_id, "Đã đổi hook")

        except publish.PublishBlocked as exc:
            self.bot.answer(callback_id, "Chưa được")
            self.say(chat_id, f"⚠️ {esc(exc)}")
            return
        except Exception as exc:  # noqa: BLE001 - lỗi mạng/Graph API trả thẳng cho người đọc
            log.exception("Thao tác bài nháp lỗi")
            self.bot.answer(callback_id, "Lỗi")
            self.say(chat_id, f"❌ {esc(exc)}")
            return

        if draft:
            self.show_draft(chat_id, draft, message_id)


COMMANDS = {
    "start": "cmd_start",
    "help": "cmd_start",
    "trogiup": "cmd_start",
    "trangthai": "cmd_status",
    "nguon": "cmd_sources",
    "themnguon": "cmd_add_source",
    "bai": "cmd_post",
    "bl": "cmd_comments",
    "binhluan": "cmd_comments",
    "dao": "cmd_mine",
    "insight": "cmd_insights",
    "nhap": "cmd_drafts",
    "lich": "cmd_schedule",
    "baocao": "cmd_report",
    "huy": "cmd_cancel",
}
