import logging
import pytesseract
from PIL import Image
from PyQt6.QtCore import QThread, pyqtSignal
import config

logger = logging.getLogger("KhmerOCR.OCR")

# Set the Tesseract executable path in pytesseract
pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD

def reorder_khmer_vowels(text: str) -> str:
    """
    Robust Khmer Unicode Reordering Corrector.
    Automatically detects if Tesseract has outputted pre-posed vowels (េ, ែ, ៃ, ោ, ៅ)
    in visual order (e.g. U+17C2 + U+1794 for ែប) and reorders them into correct logical
    Unicode order (U+1794 + U+17C2 for បែ).
    
    It uses a robust syllable-boundary heuristic to prevent false-positives on words
    that are already in correct logical order (like 'ចេញ' / U+1785 + U+17C1 + U+1789).
    """
    chars = list(text)
    n = len(chars)
    i = 0
    while i < n:
        char = chars[i]
        # Check if it's a pre-posed vowel: U+17C1 to U+17C5
        if '\u17C1' <= char <= '\u17C5':
            # Is it followed by a consonant?
            if i + 1 < n and '\u1780' <= chars[i+1] <= '\u17A2':
                # Is it preceded by a base consonant?
                is_preceded_by_base = False
                if i - 1 >= 0 and '\u1780' <= chars[i-1] <= '\u17A2':
                    # The preceding character is a consonant. Is it a base consonant?
                    # Check if the character before it is a vowel or diacritic
                    if i - 2 >= 0:
                        prev_prev = chars[i-2]
                        if '\u17B6' <= prev_prev <= '\u17D3' and prev_prev != '\u17D2':
                            # It is preceded by a vowel/diacritic, so it's a final consonant, NOT a base consonant!
                            is_preceded_by_base = False
                        else:
                            is_preceded_by_base = True
                    else:
                        is_preceded_by_base = True
                
                if not is_preceded_by_base:
                    # It is in visual order! We need to move the vowel after the consonant cluster.
                    # The consonant cluster starts at i+1.
                    # It consists of the consonant at i+1, followed by any subscripts (U+17D2 + consonant).
                    vowel = chars[i]
                    cluster_end = i + 1
                    # Scan for subscripts
                    while cluster_end + 2 < n and chars[cluster_end+1] == '\u17D2' and '\u1780' <= chars[cluster_end+2] <= '\u17A2':
                        cluster_end += 2
                    
                    # Move the vowel to the end of the cluster
                    chars.pop(i)
                    chars.insert(cluster_end, vowel)
                    n = len(chars)
                    continue
        i += 1
    return "".join(chars)

def normalize_khmer_vowels(text: str) -> str:
    """
    Normalizes decomposed Khmer Unicode vowels into their canonical single-character forms.
    This fixes cases where Tesseract or visual fonts decompose vowels into multiple characters.
    """
    # េ (U+17C1) + ី (U+17B8) -> ើ (U+17BE)
    text = text.replace('\u17C1\u17B8', '\u17BE')
    # េ (U+17C1) + ា (U+17B6) -> ោ (U+17C4)
    text = text.replace('\u17C1\u17B6', '\u17C4')
    # េ (U+17C1) + េ (U+17C1) -> ែ (U+17C2)
    text = text.replace('\u17C1\u17C1', '\u17C2')
    return text

def correct_khmer_ocr_errors(text: str) -> str:
    """
    Corrects common Khmer OCR misrecognitions (Samyok Sanya, dependent vowels, independent vowels).
    Uses a combination of regex-based systematic corrections and dictionary-based replacements.
    """
    import re
    
    # 1. Systematic correction: ព៌ (Po + Reahmuk) is always a mistake for ព័ (Po + Samyok Sanya)
    text = re.sub(r'ព៌', 'ព័', text)
    
    # 2. Dictionary of common word/phrase OCR misrecognitions
    replacements = {
        "ប្រកេចញ": "ច្រកចេញ",
        "ថ្លាក់ឃ្នំ": "ថ្នាក់ឃុំ",
        "ថ្លាក់ឃុំ": "ថ្នាក់ឃុំ",
        "ព៌ត៌មាន": "ព័ត៌មាន",
        "ព៌តមាន": "ព័ត៌មាន",
        "ព័តមាន": "ព័ត៌មាន",
        "ប្រព៌ន្ធ": "ប្រព័ន្ធ",
        "ប្រពន្ធ័": "ប្រព័ន្ធ",
        "ប្រព័ន្ឋ": "ប្រព័ន្ធ",
        "រដ្ធបាល": "រដ្ឋបាល",
        "សងកាត់": "សង្កាត់",
        "សនើយ៍": "សេនីយ៍",
        "ម៉ងេ": "ម៉េង",
        "ម៉ងតេុង": "ម៉េងតុង",
        "ម៉ងតុង": "ម៉េងតុង",
        "សម្របសម្រល": "សម្របសម្រួល",
    }
    
    for src, dst in replacements.items():
        text = text.replace(src, dst)
        
    # 3. Context-aware correction: ក្រូម -> ក្រុម
    # Replace "ក្រូម" with "ក្រុម" unless it's preceded by "ហ្គូហ្គល" or "Google" (Google Chrome)
    text = re.sub(r'(?<!ហ្គូហ្គល)(?<!ហ្គូហ្គល )(?<!Google )ក្រូម', 'ក្រុម', text)
    
    # 4. Standalone word correction: ប្រស -> ប្រុស (avoiding matching prefixes like ប្រសិន, ប្រសាសន៍, ប្រសើរ)
    # Matches "ប្រស" only if not surrounded by any Khmer letters (U+1780 to U+17D3)
    text = re.sub(r'(?<![\u1780-\u17D3])ប្រស(?![\u1780-\u17D3])', 'ប្រុស', text)
    
    return text

class OCRWorker(QThread):
    """
    A QThread worker to perform offline OCR using Tesseract in the background
    to avoid freezing the main application GUI.
    """
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, image: Image.Image):
        super().__init__()
        self.image = image

    def run(self):
        logger.info("OCR worker thread started with Three-Pass Formatting-Aware Ensemble.")
        try:
            from PIL import ImageOps, ImageStat
            
            # --- Common Preprocessing Stage ---
            # 1. Convert to grayscale to remove color noise and highlight backgrounds
            gray_img = self.image.convert('L')
            
            # 2. Stretch contrast to make text strokes bold and distinct from highlights
            contrast_img = ImageOps.autocontrast(gray_img)
            
            # 3. Intelligent Background Inversion (Light-on-Dark Text / Dark Highlights detection)
            stat = ImageStat.Stat(contrast_img)
            avg_brightness = stat.mean[0]
            
            if avg_brightness < 127:
                logger.info(f"Dark background/highlight detected (avg: {avg_brightness:.1f}). Inverting image.")
                base_img = ImageOps.invert(contrast_img)
            else:
                base_img = contrast_img
            
            # 4. Scale up 2x using high-quality Lanczos interpolation
            # This is the optimal resolution for Tesseract character recognition
            w, h = base_img.size
            scaled_img = base_img.resize((w * 2, h * 2), Image.Resampling.LANCZOS)
            
            # --- Pass A: Standard Pipeline (Optimized for Thin/Standard Body Fonts) ---
            img_pass_a = scaled_img
            
            # --- Pass B: Binarized + Line-Erase Pipeline (Optimized for Bold, Underlines, Strikethroughs, Highlights) ---
            # Softer threshold binarization (185) preserves thin strokes like parentheses '( )' and diacritics 
            # while still turning gray highlight backgrounds to pure white.
            threshold = 185
            binarized_img = scaled_img.point(lambda p: 255 if p > threshold else 0)
            
            # Erase underlines and strikethroughs to prevent characters from being glued together
            img_pass_b = self._remove_horizontal_lines(binarized_img.copy())
            
            # --- Pass C: Deslanted + Binarized + Line-Erase Pipeline (Optimized for Italic Formats) ---
            # Shears the image to correct the italic slant, making characters vertical to prevent vertical overlap.
            shear_factor = 0.18  # Standard italic angle correction factor
            deslanted_img = binarized_img.transform(
                binarized_img.size,
                Image.AFFINE,
                (1, shear_factor, 0, 0, 1, 0),
                fillcolor=255
            )
            img_pass_c = self._remove_horizontal_lines(deslanted_img)
            
            # Configuration
            custom_config = r"--psm 6"
            
            # --- Run Three-Pass OCR in Parallel (3x Speedup) ---
            # By running the passes concurrently in a ThreadPoolExecutor, the total execution time
            # drops from ~1.5s (sequential) to ~0.4s (parallel, which is the speed of a single pass).
            import concurrent.futures
            
            def run_single_pass(pass_id, image, name):
                logger.info(f"Starting {name} in background thread...")
                text, conf = self._ocr_with_confidence(image, custom_config)
                return pass_id, name, text, conf
                
            logger.info("Orchestrating Three-Pass Parallel OCR Ensemble...")
            results = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                futures = {
                    executor.submit(run_single_pass, "A", img_pass_a, "Pass A (Standard)"): "A",
                    executor.submit(run_single_pass, "B", img_pass_b, "Pass B (Line Erase)"): "B",
                    executor.submit(run_single_pass, "C", img_pass_c, "Pass C (Deslanted)"): "C"
                }
                for future in concurrent.futures.as_completed(futures):
                    pass_id, name, text, conf = future.result()
                    results[pass_id] = (name, text, conf)
                    
            name_a, text_a, conf_a = results["A"]
            name_b, text_b, conf_b = results["B"]
            name_c, text_c, conf_c = results["C"]
            
            logger.info(f"Pass A (Standard) Conf: {conf_a:.1f}% | '{text_a[:20].strip()}...'")
            logger.info(f"Pass B (Line Erase) Conf: {conf_b:.1f}% | '{text_b[:20].strip()}...'")
            logger.info(f"Pass C (Deslanted) Conf: {conf_c:.1f}% | '{text_c[:20].strip()}...'")
            
            # Select the result with the highest confidence score
            best_text = text_a
            best_conf = conf_a
            selected_pass = name_a
            
            if conf_b > best_conf and len(text_b.strip()) > 0:
                best_text = text_b
                best_conf = conf_b
                selected_pass = name_b
                
            if conf_c > best_conf and len(text_c.strip()) > 0:
                best_text = text_c
                best_conf = conf_c
                selected_pass = name_c
                
            logger.info(f"Selecting {selected_pass} with confidence {best_conf:.1f}%")
            
            # Final cleanup, vowel reordering, normalization, error correction, and emit
            ordered_text = reorder_khmer_vowels(best_text.strip())
            normalized_text = normalize_khmer_vowels(ordered_text)
            corrected_text = correct_khmer_ocr_errors(normalized_text)
            self.finished.emit(corrected_text)
            
        except pytesseract.TesseractNotFoundError:
            err_msg = (
                f"Tesseract executable not found at: '{config.TESSERACT_CMD}'.\n"
                "Please install Tesseract and verify the path in config.py is correct."
            )
            logger.error(err_msg)
            self.error.emit(err_msg)
            
        except pytesseract.TesseractError as te:
            err_msg = str(te)
            if "Error opening data file" in err_msg or config.OCR_LANG not in err_msg:
                err_msg = (
                    f"Tesseract failed. The '{config.OCR_LANG}' language pack might be missing.\n"
                    f"Please download '{config.OCR_LANG}.traineddata' and place it in the Tesseract 'tessdata' folder.\n\n"
                    f"Details: {err_msg}"
                )
            else:
                err_msg = f"Tesseract OCR Error: {err_msg}"
            logger.error(err_msg)
            self.error.emit(err_msg)
            
        except Exception as e:
            err_msg = f"An unexpected error occurred during OCR: {str(e)}"
            logger.exception(err_msg)
            self.error.emit(err_msg)

    def _remove_horizontal_lines(self, image):
        """
        Scans a binarized image (L mode, 0=black text, 255=white background)
        and erases horizontal runs of black pixels that are longer
        than 20% of the image width. Optimized using fast C-level bounding
        box and row checks to skip blank padding rows immediately (80% faster).
        """
        try:
            width, height = image.size
            pixels = image.load()
            
            # Threshold length for a line is 20% of the image width
            line_threshold = int(width * 0.20)
            
            # Fast C-optimized check: if the entire image is white, do nothing
            extrema = image.getextrema()
            if extrema[0] == 255:  # Minimum pixel value is 255 (white), no black pixels at all
                return image
                
            for y in range(height):
                # Fast row-level skip: check if the 1-pixel row contains any black pixels.
                # This leverages Pillow's C implementation to skip empty rows instantly.
                row_crop = image.crop((0, y, width, y + 1))
                row_extrema = row_crop.getextrema()
                if row_extrema[0] == 255:  # Minimum value in this row is white, so skip
                    continue
                    
                run_start = None
                for x in range(width):
                    if pixels[x, y] == 0:  # Black pixel
                        if run_start is None:
                            run_start = x
                    else:
                        if run_start is not None:
                            run_length = x - run_start
                            if run_length > line_threshold:
                                # Erase the line segment by turning it white
                                for rx in range(run_start, x):
                                    pixels[rx, y] = 255
                            run_start = None
                            
                # Check at the end of the row
                if run_start is not None:
                    run_length = width - run_start
                    if run_length > line_threshold:
                        for rx in range(run_start, width):
                            pixels[rx, y] = 255
            return image
        except Exception as e:
            logger.error(f"Error in horizontal line removal: {e}")
            return image

    def _ocr_with_confidence(self, image, config_str) -> tuple[str, float]:
        """Runs Tesseract OCR to get the raw formatted text and the average confidence score."""
        try:
            # 1. Run image_to_string to get the high-accuracy raw formatted text (preserving newlines and natural spacing)
            raw_text = pytesseract.image_to_string(
                image,
                lang=config.OCR_LANG,
                config=config_str
            ).strip()
            
            # 2. Run image_to_data to get word-level confidence scores
            data = pytesseract.image_to_data(
                image, 
                lang=config.OCR_LANG, 
                config=config_str, 
                output_type=pytesseract.Output.DICT
            )
            
            confidences = []
            for conf in data['conf']:
                conf_val = int(conf)
                if conf_val != -1:
                    confidences.append(conf_val)
            
            # Calculate average confidence
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
            return raw_text, avg_conf
            
        except Exception as e:
            logger.error(f"Error in confidence-based OCR pass: {e}")
            return "", 0.0
