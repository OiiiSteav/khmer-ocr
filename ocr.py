import logging
import pytesseract
from PIL import Image
from PyQt6.QtCore import QThread, pyqtSignal
import config

logger = logging.getLogger("KhmerOCR.OCR")

# Set the Tesseract executable path in pytesseract
pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD

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
            from PIL import ImageOps, ImageStat, Image
            
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
            # Threshold binarization converts gray/highlight backgrounds to pure white, erasing highlights.
            threshold = 127
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
            
            # --- Run Three-Pass OCR and Compare Confidence Scores ---
            logger.info("Running Pass A (Standard Grayscale)...")
            text_a, conf_a = self._ocr_with_confidence(img_pass_a, custom_config)
            
            logger.info("Running Pass B (Binarized + Line Erase)...")
            text_b, conf_b = self._ocr_with_confidence(img_pass_b, custom_config)
            
            logger.info("Running Pass C (Deslanted + Line Erase)...")
            text_c, conf_c = self._ocr_with_confidence(img_pass_c, custom_config)
            
            logger.info(f"Pass A (Standard) Conf: {conf_a:.1f}% | '{text_a[:20]}...'")
            logger.info(f"Pass B (Line Erase) Conf: {conf_b:.1f}% | '{text_b[:20]}...'")
            logger.info(f"Pass C (Deslanted) Conf: {conf_c:.1f}% | '{text_c[:20]}...'")
            
            # Select the result with the highest confidence score
            best_text = text_a
            best_conf = conf_a
            selected_pass = "Pass A (Standard)"
            
            if conf_b > best_conf and len(text_b.strip()) > 0:
                best_text = text_b
                best_conf = conf_b
                selected_pass = "Pass B (Line Erase)"
                
            if conf_c > best_conf and len(text_c.strip()) > 0:
                best_text = text_c
                best_conf = conf_c
                selected_pass = "Pass C (Deslanted)"
                
            logger.info(f"Selecting {selected_pass} with confidence {best_conf:.1f}%")
            
            # Final cleanup and emit
            final_text = best_text.strip()
            self.finished.emit(final_text)
            
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
        and erases contiguous horizontal runs of black pixels that are longer
        than 20% of the image width. This removes underlines and strikethroughs
        without affecting vertical character strokes.
        """
        try:
            width, height = image.size
            pixels = image.load()
            
            # Threshold length for a line is 20% of the image width
            line_threshold = int(width * 0.20)
            
            for y in range(height):
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
        """Runs Tesseract OCR and calculates the average confidence score for recognized words."""
        try:
            data = pytesseract.image_to_data(
                image, 
                lang=config.OCR_LANG, 
                config=config_str, 
                output_type=pytesseract.Output.DICT
            )
            
            # Filter out empty text results and metadata (-1 confidence)
            confidences = []
            words = []
            
            for i in range(len(data['text'])):
                word = data['text'][i].strip()
                conf = int(data['conf'][i])
                
                if conf != -1:
                    confidences.append(conf)
                    if word != "":
                        words.append(word)
            
            # Combine recognized words
            text = " ".join(words).strip()
            
            # Calculate average confidence
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
            return text, avg_conf
            
        except Exception as e:
            logger.error(f"Error in confidence-based OCR pass: {e}")
            return "", 0.0
            
            # Clean up the output text
            cleaned_text = text.strip()
            
            logger.info(f"OCR complete. Characters recognized: {len(cleaned_text)}")
            self.finished.emit(cleaned_text)
            
        except pytesseract.TesseractNotFoundError:
            err_msg = (
                f"Tesseract executable not found at: '{config.TESSERACT_CMD}'.\n"
                "Please make sure Tesseract is installed and the path in config.py is correct."
            )
            logger.error(err_msg)
            self.error.emit(err_msg)
            
        except pytesseract.TesseractError as te:
            err_msg = str(te)
            # If the error is due to missing language pack
            if "Error opening data file" in err_msg or config.OCR_LANG not in err_msg:
                err_msg = (
                    f"Tesseract failed. The '{config.OCR_LANG}' language pack might be missing.\n"
                    f"Please download '{config.OCR_LANG}.traineddata' and place it in your Tesseract 'tessdata' folder.\n\n"
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
