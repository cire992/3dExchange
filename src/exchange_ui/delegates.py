"""Painting: browser bricks and sidebar rows, as in the mockup."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from exchange_ui import theme
from exchange_ui.models import BRICK, COUNT, DETAIL, KIND, THUMBNAIL, meta_line

BRICK_SIZE = QSize(156, 186)
_PAD = 8


class BrickDelegate(QStyledItemDelegate):
    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return BRICK_SIZE

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        brick = index.data(BRICK)
        if brick is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(option.rect).adjusted(4, 4, -4, -4)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        path = QPainterPath()
        path.addRoundedRect(card, 8, 8)
        painter.fillPath(path, theme.color(theme.CARD_HOVER if hovered else theme.SURFACE))
        border = theme.ACCENT if selected else (theme.WARN_BORDER if brick.unidentified else theme.BORDER)
        pen = QPen(theme.color(border), 2 if selected else 1)
        if brick.unidentified and not selected:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawPath(path)

        thumb = QRectF(card.left() + _PAD, card.top() + _PAD, card.width() - 2 * _PAD, card.width() - 2 * _PAD - 34)
        thumb_path = QPainterPath()
        thumb_path.addRoundedRect(thumb, 6, 6)
        painter.fillPath(thumb_path, theme.color(theme.CARD))
        image = index.data(THUMBNAIL)
        if image is not None and not image.isNull():
            scaled = image.scaled(int(thumb.width()), int(thumb.height()), Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
            x = thumb.left() + (thumb.width() - scaled.width()) / 2
            y = thumb.top() + (thumb.height() - scaled.height()) / 2
            painter.setClipPath(thumb_path)
            painter.drawImage(QPointF(x, y), scaled)
            painter.setClipping(False)
        else:
            draw_cube(painter, thumb.center(), 14, theme.color(theme.MUTED))

        if brick.format and brick.type_id != "product":
            badge_font = theme.mono_font(7)
            painter.setFont(badge_font)
            text = brick.format.lstrip(".").upper()
            width = painter.fontMetrics().horizontalAdvance(text) + 10
            badge = QRectF(thumb.right() - width - 5, thumb.top() + 5, width, 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.color(theme.BG))
            painter.drawRoundedRect(badge, 3, 3)
            painter.setPen(theme.color(theme.MUTED_2))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
        if brick.unidentified:
            painter.setFont(theme.ui_font(7, QFont.Weight.DemiBold))
            label = QRectF(thumb.left() + 5, thumb.top() + 5, 70, 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.color(theme.WARN_BG))
            painter.drawRoundedRect(label, 3, 3)
            painter.setPen(theme.color(theme.WARN_LIGHT))
            painter.drawText(label, Qt.AlignmentFlag.AlignCenter, "Unidentified")

        text_rect = QRectF(card.left() + _PAD, thumb.bottom() + 6, card.width() - 2 * _PAD, 18)
        painter.setFont(theme.ui_font(9, QFont.Weight.DemiBold))
        painter.setPen(theme.color(theme.TEXT))
        name = painter.fontMetrics().elidedText(brick.name, Qt.TextElideMode.ElideRight, int(text_rect.width()))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
        meta_rect = QRectF(text_rect.left(), text_rect.bottom(), text_rect.width(), 16)
        painter.setFont(theme.ui_font(7.5))
        painter.setPen(theme.color(theme.MUTED_2))
        meta = painter.fontMetrics().elidedText(f"{brick.type_name} · {meta_line(brick)}".strip(" ·"),
                                                Qt.TextElideMode.ElideRight, int(meta_rect.width()))
        painter.drawText(meta_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, meta)
        painter.restore()


def draw_cube(painter: QPainter, center: QPointF, r: float, color: QColor) -> None:
    """The mockup's placeholder: an outlined isometric cube."""
    painter.save()
    painter.setPen(QPen(color, 1.4))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy, h = center.x(), center.y(), r * 0.5
    upper_left, upper_right = QPointF(cx - r, cy - h), QPointF(cx + r, cy - h)
    bottom, mid = QPointF(cx, cy + r), QPointF(cx, cy)
    painter.drawPolygon(QPolygonF([QPointF(cx, cy - r), upper_right, QPointF(cx + r, cy + h), bottom,
                                   QPointF(cx - r, cy + h), upper_left]))
    for corner in (upper_left, upper_right, bottom):
        painter.drawLine(mid, corner)
    painter.restore()


class SidebarDelegate(QStyledItemDelegate):
    """Section headers in small caps, counts right-aligned, layer labels in grey."""

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        size = super().sizeHint(option, index)
        if index.data(KIND) == "section":
            return QSize(size.width(), 30)
        return QSize(size.width(), max(size.height(), 28))

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        kind = index.data(KIND)
        if kind == "section":
            painter.save()
            painter.setFont(theme.ui_font(7, QFont.Weight.DemiBold))
            painter.setPen(theme.color(theme.MUTED))
            rect = QRect(option.rect).adjusted(0, 10, 0, 0)
            painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, index.data())
            painter.restore()
            return
        count, detail = index.data(COUNT), index.data(DETAIL)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        widget = option.widget
        style = widget.style() if widget else None
        if style:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        painter.save()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        rect = QRect(option.rect).adjusted(6, 0, -8, 0)
        painter.setFont(theme.ui_font(9, QFont.Weight.DemiBold if kind == "environment" else QFont.Weight.Normal))
        painter.setPen(theme.color(theme.ACCENT_LIGHT if selected else theme.TEXT_2))
        count_text = f"{count:,}" if isinstance(count, int) else ""
        metrics = painter.fontMetrics()
        count_width = metrics.horizontalAdvance(count_text) + 8
        name = metrics.elidedText(index.data(), Qt.TextElideMode.ElideRight, rect.width() - count_width - 50)
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
        if detail:
            painter.setFont(theme.ui_font(7.5))
            painter.setPen(theme.color(theme.MUTED))
            painter.drawText(rect.adjusted(metrics.horizontalAdvance(name) + 6, 0, 0, 0),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"· {detail}")
        if count_text:
            painter.setFont(theme.ui_font(8))
            painter.setPen(theme.color(theme.ACCENT_LIGHT if selected else theme.MUTED))
            painter.drawText(rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, count_text)
        painter.restore()
