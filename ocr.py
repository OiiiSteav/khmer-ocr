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
        logger.info("OCR worker thread started with Dual-Pass Ensemble.")
        try:
            from PIL import ImageOps, ImageStat
            
            # --- Common Preprocessing Stage ---
            # 1. Convert to grayscale to remove color noise
            gray_img = self.image.convert('L')
            
            # 2. Stretch contrast to enhance faint outlines
            contrast_img = ImageOps.autocontrast(gray_img)
            
            # 3. Intelligent Background Inversion (Light-on-Dark Text detection)
            stat = ImageStat.Stat(contrast_img)
            avg_brightness = stat.mean[0]
            
            if avg_brightness < 127:
                logger.info(f"Dark background detected (avg brightness: {avg_brightness:.1f}). Inverting image.")
                base_img = ImageOps.invert(contrast_img)
            else:
                base_img = contrast_img
            
            # 4. Scale up 2x using high-quality Lanczos interpolation
            w, h = base_img.size
            scaled_img = base_img.resize((w * 2, h * 2), Image.Resampling.LANCZOS)
            
            # --- Pass A: Standard Pipeline (Optimized for Thin/Body Fonts) ---
            # Thin fonts (e.g., Battambang, Content) perform best with smooth grayscale anti-aliasing.
            # Binarization can sometimes break thin strokes, so we keep the smooth scaled image.
            img_pass_a = scaled_img
            
            # --- Pass B: Binarized Pipeline (Optimized for Thick/Decorative Fonts like Khmer Moul) ---
            # Thick fonts perform best when anti-aliasing is stripped, leaving razor-sharp boundaries.
            # This prevents loops and sub-consonants from bleeding together into solid black blobs.
            threshold = 127
            img_pass_b = scaled_img.point(lambda p: 255 if p > threshold else 0)
            
            # Configuration
            custom_config = r"--psm 6"
            
            # --- Run Dual-Pass OCR and Compare Confidence Scores ---
            logger.info("Running Pass A (Standard Grayscale)...")
            text_a, conf_a = self._ocr_with_confidence(img_pass_a, custom_config)
            
            logger.info("Running Pass B (Binarized High-Contrast)...")
            text_b, conf_b = self._ocr_with_confidence(img_pass_b, custom_config)
            
            logger.info(f"Pass A (Standard) Confidence: {conf_a:.1f}% | Recognized: '{text_a[:30]}...'")
            logger.info(f"Pass B (Binarized) Confidence: {conf_b:.1f}% | Recognized: '{text_b[:30]}...'")
            
            # Select the result with the higher average confidence score
            if conf_b > conf_a and len(text_b.strip()) > 0:
                logger.info(f"Selecting Pass B (Binarized) for higher confidence ({conf_b:.1f}% vs {conf_a:.1f}%). Optimized for decorative fonts.")
                final_text = text_b
            else:
                logger.info(f"Selecting Pass A (Standard) for higher confidence ({conf_a:.1f}% vs {conf_b:.1f}%). Optimized for standard fonts.")
                final_text = text_a
            
            # Final clean up
            final_text_cleaned = final_text.strip()
            self.finished.emit(final_text_cleaned)
            
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
