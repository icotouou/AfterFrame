import colorsys

from PySide6.QtGui import QColor, QPixmap
from PySide6.QtCore import Qt


class ColorExtractor:
    """Extract dominant colors from an album cover for background tinting."""

    @staticmethod
    def extract_dominant_color(pixmap: QPixmap, sample_size: int = 64) -> QColor:
        """Return the dominant color of *pixmap* as a QColor.

        The image is downscaled for speed, very dark/very bright pixels are
        ignored, and the average of the remaining saturated colors is returned.
        """
        if pixmap is None or pixmap.isNull():
            return QColor(45, 50, 70)

        small = pixmap.scaled(
            sample_size,
            sample_size,
            Qt.IgnoreAspectRatio,
            Qt.FastTransformation,
        )
        image = small.toImage()

        total_r = total_g = total_b = count = 0
        for y in range(image.height()):
            for x in range(image.width()):
                color = image.pixelColor(x, y)
                lightness = color.lightness()
                # Skip near-black and near-white pixels.
                if lightness < 25 or lightness > 230:
                    continue
                total_r += color.red()
                total_g += color.green()
                total_b += color.blue()
                count += 1

        if count == 0:
            return QColor(45, 50, 70)

        return QColor(total_r // count, total_g // count, total_b // count)

    @staticmethod
    def extract_palette(pixmap: QPixmap, count: int = 5, sample_size: int = 64) -> list:
        """Return up to *count* distinct dominant colors of *pixmap*.

        Pixels are quantized into coarse RGB bins, the busiest bins are picked
        greedily (skipping bins too similar to an already-picked color), and
        each picked color is refined to the average of its actual pixels.
        """
        if pixmap is None or pixmap.isNull():
            return []

        small = pixmap.scaled(
            sample_size,
            sample_size,
            Qt.IgnoreAspectRatio,
            Qt.FastTransformation,
        )
        image = small.toImage()

        # Quantize to 4 bits per channel (4096 bins) and accumulate averages.
        bins = {}
        for y in range(image.height()):
            for x in range(image.width()):
                color = image.pixelColor(x, y)
                lightness = color.lightness()
                if lightness < 20 or lightness > 235:
                    continue
                r, g, b = color.red(), color.green(), color.blue()
                key = (r >> 4) << 8 | (g >> 4) << 4 | (b >> 4)
                entry = bins.get(key)
                if entry is None:
                    bins[key] = [r, g, b, 1]
                else:
                    entry[0] += r
                    entry[1] += g
                    entry[2] += b
                    entry[3] += 1

        if not bins:
            return []

        ranked = sorted(
            ((key, e) for key, e in bins.items()),
            key=lambda item: item[1][3],
            reverse=True,
        )

        palette = []
        min_dist_sq = 52 * 52
        for _key, (r_sum, g_sum, b_sum, n) in ranked:
            candidate = QColor(r_sum // n, g_sum // n, b_sum // n)
            for chosen in palette:
                dr = candidate.red() - chosen.red()
                dg = candidate.green() - chosen.green()
                db = candidate.blue() - chosen.blue()
                if dr * dr + dg * dg + db * db < min_dist_sq:
                    break
            else:
                palette.append(candidate)
                if len(palette) >= count:
                    break
        return palette

    @staticmethod
    def darken_color(
        color: QColor, lightness_factor: float = 0.35, saturation_factor: float = 0.7
    ) -> QColor:
        """Darken and desaturate *color* so it works as a background tone."""
        h, l, s = colorsys.rgb_to_hls(
            color.red() / 255.0,
            color.green() / 255.0,
            color.blue() / 255.0,
        )
        new_l = max(0.04, l * lightness_factor)
        new_s = max(0.0, s * saturation_factor)
        r, g, b = colorsys.hls_to_rgb(h, new_l, new_s)
        return QColor(int(r * 255), int(g * 255), int(b * 255))

    @staticmethod
    def to_hex(color: QColor) -> str:
        return f"#{color.red():02x}{color.green():02x}{color.blue():02x}"

    @staticmethod
    def complementary_text_color(color: QColor) -> QColor:
        """Return white or black depending on which contrasts better."""
        luminance = (0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()) / 255
        return QColor(255, 255, 255) if luminance < 0.5 else QColor(20, 20, 20)
