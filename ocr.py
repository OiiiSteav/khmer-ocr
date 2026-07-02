import os
import logging
import tempfile
import pytesseract
from PIL import Image
from PyQt6.QtCore import QThread, pyqtSignal
import config

logger = logging.getLogger("KhmerOCR.OCR")

# Set the Tesseract executable path in pytesseract
pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD

# Try importing Kiri OCR (Deep learning-based OCR)
HAS_KIRI_OCR = False
try:
    from kiri_ocr import OCR as KiriOCR
    HAS_KIRI_OCR = True
    logger.info("Kiri OCR library successfully imported.")
except ImportError:
    logger.warning("Kiri OCR library not found. Falling back to Tesseract.")

# Try importing Seanghay's Khmer Normalizer (Linguistic text normalization)
HAS_KHMER_NORMALIZER = False
try:
    from khmernormalizer import normalize as khmer_normalize
    HAS_KHMER_NORMALIZER = True
    logger.info("Seanghay's Khmer Normalizer successfully imported.")
except ImportError:
    logger.warning("Seanghay's Khmer Normalizer not found. Using custom normalization.")

_kiri_ocr_instance = None

def get_kiri_ocr_instance():
    """Returns a cached singleton instance of Kiri OCR to avoid reloading models on every run."""
    global _kiri_ocr_instance
    if _kiri_ocr_instance is None and HAS_KIRI_OCR:
        try:
            logger.info("Loading Kiri OCR models (ONNX)...")
            # Kiri OCR supports "accurate", "fast", and "beam" decoding
            _kiri_ocr_instance = KiriOCR(decode_method="accurate")
            logger.info("Kiri OCR models loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Kiri OCR: {e}")
            _kiri_ocr_instance = None
    return _kiri_ocr_instance

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
    Advanced Khmer OCR Error Corrector.
    Uses high-precision regexes with character classes representing common visual 
    and typing confusions in Khmer script to automatically correct misrecognized words.
    """
    import re
    
    # 1. Systematic correction: ព៌ (Po + Reahmuk) is always a mistake for ព័ (Po + Samyok Sanya)
    text = re.sub(r'ព៌', 'ព័', text)
    
    # 2. Typing correction: Normalize incorrect subscript ordering in 'មន្ត្រី'
    # 'មន្រ្តី' (incorrect: Coeng Ro + Coeng Ta) -> 'មន្ត្រី' (correct: Coeng Ta + Coeng Ro)
    text = text.replace('\u1798\u1793\u17D2\u179A\u17D2\u178F\u17B8', '\u1798\u1793\u17D2\u178F\u17D2\u179A\u17B8')
    
    # 3. Regex-based smart corrections for common words
    # These use character classes to match visual confusions (e.g. ុ vs ូ, ័ vs ៌, ន vs ល, ឋ vs ឌ vs ធ)
    
    # Correct 'ព័ត៌មាន' (matches: ព៌ត៌មាន, ព័តមាន, ប៌ត៌មាន, ព័ត៌មាល, etc.)
    text = re.sub(r'[ពប][័៌៍]ត[៌័៍]?[មណ][ាា]?[នល]', 'ព័ត៌មាន', text)
    
    # Correct 'ប្រព័ន្ធ' (matches: ប្រព៌ន្ធ, ប្រពន្ធ័, ប្រព័ន្ឋ, ប្រពល្ឌ, etc.)
    text = re.sub(r'ប្រ[ពប][័៌៍]?[នល]្?[ធឋឌ][៍័]?', 'ប្រព័ន្ធ', text)
    text = re.sub(r'ប្រ[ពប][័៌៍][នល]្[ធឋឌ]', 'ប្រព័ន្ធ', text)
    
    # Correct 'ក្រុមហ៊ុន' (matches: ក្រូមហ៊ុន, ក្រុមហ៊ុន, ក្រូមហ៊ូន, etc.)
    text = re.sub(r'ក្រ[ុូ]ម[ហវ][ុូ]ន', 'ក្រុមហ៊ុន', text)
    
    # Correct 'ច្រកចេញ' & 'ច្រកចេញចូល' (matches: ប្រកេចញ, ប្រកេចញចូល, ច្រកេចញ, etc.)
    text = re.sub(r'[ច្រប្រវ្រ]ក[េ]?[ចប]ញ[ចូលចល]+', 'ច្រកចេញចូល', text)
    text = re.sub(r'[ច្រប្រវ្រ]ក[េ]?[ចប]ញ', 'ច្រកចេញ', text)
    
    # Correct 'ថ្នាក់ឃុំ' (matches: ថ្លាក់ឃ្នំ, ថ្លាក់ឃុំ, ថ្នាក់ឃ្នំ, etc.)
    text = re.sub(r'ថ[្ន្ល]ាក់[ឃគ][្នុូ]?[ំម]', 'ថ្នាក់ឃុំ', text)
    
    # Correct 'សង្កាត់' (matches: សងកាត់, សង្កត, etc.)
    text = re.sub(r'សង[្]?កា?[តថ]់', 'សង្កាត់', text)
    
    # Correct 'សម្របសម្រួល' (matches: សម្របសម្រល, សម្របសម្រូល, etc.)
    text = re.sub(r'សម្របសម្រ[ួូ]?ល', 'សម្របសម្រួល', text)
    
    # Correct 'សេនីយ៍' (matches: សនើយ៍, សេលីយ៍, សនីយ៍, etc.)
    # This automatically fixes 'អនុសនើយ៍' -> 'អនុសេនីយ៍' and 'វរសនើយ៍' -> 'វរសេនីយ៍'
    text = re.sub(r'ស[េ]?[នល][ីើើ]យ៍', 'សេនីយ៍', text)
    
    # Correct 'នាយកដ្ឋាន' (matches: នាយកដាន, នាយកថាល, etc.)
    text = re.sub(r'នាយក[ដឌឋ]ា[នល]', 'នាយកដ្ឋាន', text)
    text = re.sub(r'នាយក[ដឌឋ]ាន', 'នាយកដ្ឋាន', text)
    
    # Correct 'អគ្គនាយកដ្ឋាន'
    text = re.sub(r'អគ្គនាយក[ដឌឋ]ា[នល]', 'អគ្គនាយកដ្ឋាន', text)
    
    # Correct 'គ្រប់គ្រង'
    text = re.sub(r'គ្រ[ុូ]បគ្រ[ុូ]?ង', 'គ្រប់គ្រង', text)
    
    # Correct 'ក្រសួង'
    text = re.sub(r'ក្រស[ួូ]ង', 'ក្រសួង', text)
    
    # Correct 'សេវា'
    text = re.sub(r'សេវ[ាា]', 'សេវា', text)
    
    # Correct 'អត្តសញ្ញាណកម្ម'
    text = re.sub(r'អត្តសញ[្]?ញាណក[មម]', 'អត្តសញ្ញាណកម្ម', text)
    
    # Correct 'អាសយដ្ឋាន'
    text = re.sub(r'អាសយ[ដឌឋ]ា[នល]', 'អាសយដ្ឋាន', text)
    
    # Correct 'ទូរស័ព្ទ'
    text = re.sub(r'ទូរស[័៌]ព្[ទធ]', 'ទូរស័ព្ទ', text)
    
    # Correct 'អ៊ីមែល'
    text = re.sub(r'អ៊ីម[ែេ]ល', 'អ៊ីមែល', text)
    
    # Correct 'កម្ពុជា'
    text = re.sub(r'ក[មម]្ពុជ[ាា]', 'កម្ពុជា', text)
    
    # Correct 'ភ្នំពេញ'
    text = re.sub(r'ភ្ន[ំម]ពេញ', 'ភ្នំពេញ', text)
    
    # 4. Context-aware correction for 'ក្រូម' -> 'ក្រុម' (if not part of Google Chrome)
    text = re.sub(r'(?<!ហ្គូហ្គល)(?<!ហ្គូហ្គល )(?<!Google )ក្រ[ុូ]ម', 'ក្រុម', text)
    
    # 5. Standalone word correction: ប្រស -> ប្រុស (avoiding matching prefixes like ប្រសិន, ប្រសាសន៍, ប្រសើរ)
    # Matches "ប្រស" only if not surrounded by any Khmer letters (U+1780 to U+17D3)
    text = re.sub(r'(?<![\u1780-\u17D3])ប្រស(?![\u1780-\u17D3])', 'ប្រុស', text)
    
    return text

import urllib.request

KHMER_DICT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "khmer_dict.txt")

_khmer_dictionary = None
_khmer_dict_by_len = None

def load_khmer_dictionary():
    """Loads the Khmer dictionary from a local file, downloading and merging sources if not present."""
    global _khmer_dictionary, _khmer_dict_by_len
    if _khmer_dictionary is not None:
        return _khmer_dictionary, _khmer_dict_by_len
        
    # Check if local file exists, if not download and merge sources
    if not os.path.exists(KHMER_DICT_FILE):
        try:
            logger.info("Consolidating Khmer dictionary from SIL sources...")
            merged_words = set()
            urls = [
                "https://raw.githubusercontent.com/silnrsi/khmerlbdict/master/src/KHSV.txt",
                "https://raw.githubusercontent.com/silnrsi/khmerlbdict/master/src/seafreq.txt"
            ]
            for url in urls:
                logger.info(f"Downloading dictionary source: {url}")
                req = urllib.request.Request(
                    url, 
                    headers={'User-Agent': 'Mozilla/5.0'}
                )
                with urllib.request.urlopen(req) as response:
                    content = response.read().decode('utf-8-sig')
                    for line in content.splitlines():
                        parts = line.strip().split("\t")
                        if parts:
                            word = parts[0].strip()
                            # Skip header, metadata and empty lines
                            if word and not word.startswith("Source:") and not word.startswith("---") and not word.startswith("Title:") and not word.startswith("Description:"):
                                merged_words.add(word)
                                
            # Save the merged dictionary locally (one word per line, sorted)
            with open(KHMER_DICT_FILE, "w", encoding="utf-8") as f:
                for word in sorted(merged_words):
                    f.write(f"{word}\n")
            logger.info(f"Consolidated dictionary saved to {KHMER_DICT_FILE} with {len(merged_words)} words.")
        except Exception as e:
            logger.error(f"Failed to consolidate Khmer dictionary: {e}")
            if os.path.exists(KHMER_DICT_FILE):
                try:
                    os.remove(KHMER_DICT_FILE)
                except:
                    pass
            return set(), {}
            
    # Load dictionary words from consolidated local file
    dictionary = set()
    dict_by_len = {}
    try:
        with open(KHMER_DICT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                word = line.strip()
                if word:
                    dictionary.add(word)
                    l = len(word)
                    if l not in dict_by_len:
                        dict_by_len[l] = []
                    dict_by_len[l].append(word)
        logger.info(f"Loaded {len(dictionary)} words into Khmer dictionary.")
    except Exception as e:
        logger.error(f"Failed to read Khmer dictionary file: {e}")
        
    _khmer_dictionary = dictionary
    _khmer_dict_by_len = dict_by_len
    return _khmer_dictionary, _khmer_dict_by_len

def edit_distance(s1: str, s2: str) -> int:
    """Calculates the Levenshtein distance between two strings."""
    if len(s1) > len(s2):
        s1, s2 = s2, s1
    distances = range(len(s1) + 1)
    for i2, c2 in enumerate(s2):
        distances_ = [i2 + 1]
        for i1, c1 in enumerate(s1):
            if c1 == c2:
                distances_.append(distances[i1])
            else:
                distances_.append(1 + min((distances[i1], distances[i1 + 1], distances_[-1])))
        distances = distances_
    return distances[-1]

def correct_spelling_with_dictionary(text: str) -> str:
    """
    Verifies and corrects Khmer words using the SIL Khmer dictionary.
    1. Segments Khmer text using a greedy MaxMatch algorithm.
    2. Checks each Khmer token against the dictionary.
    3. If misspelled (not in dictionary), finds candidate words of similar length with edit distance = 1.
    4. Automatically replaces obvious typos to improve OCR accuracy.
    """
    dictionary, dict_by_len = load_khmer_dictionary()
    if not dictionary:
        return text
        
    # MaxMatch Segmentation
    max_len = 12
    words = []
    i = 0
    n = len(text)
    
    while i < n:
        char = text[i]
        # Check if it's a Khmer character (range U+1780 to U+17D3) or a subconsonant marker/diacritic
        is_khmer = ('\u1780' <= char <= '\u17D3') or ('\u17D2' <= char <= '\u17D3')
        if not is_khmer:
            # Find run of non-Khmer characters (spaces, English, punctuation)
            j = i
            while j < n and not (('\u1780' <= text[j] <= '\u17D3') or ('\u17D2' <= text[j] <= '\u17D3')):
                j += 1
            words.append(text[i:j])
            i = j
            continue
            
        # Try to find the longest matching word in the dictionary
        matched = False
        for length in range(min(max_len, n - i), 0, -1):
            sub = text[i : i + length]
            if sub in dictionary:
                words.append(sub)
                i += length
                matched = True
                break
                
        if not matched:
            # We didn't match any dictionary word. Group consecutive non-matching characters
            # to form a candidate word token (instead of single characters which are ignored).
            run_start = i
            while i < n:
                # Stop if we hit a non-Khmer character
                if not (('\u1780' <= text[i] <= '\u17D3') or ('\u17D2' <= text[i] <= '\u17D3')):
                    break
                # Stop if we find a dictionary word matching starting at this index (after the start)
                if i > run_start:
                    has_dict_match = False
                    for length in range(min(max_len, n - i), 0, -1):
                        if text[i : i + length] in dictionary:
                            has_dict_match = True
                            break
                    if has_dict_match:
                        break
                i += 1
            words.append(text[run_start:i])
            
    # Correct misspelled words
    corrected_words = []
    idx = 0
    num_words = len(words)
    
    while idx < num_words:
        token = words[idx]
        
        # Check if we can combine token with next_token for a correction
        if idx < num_words - 1:
            next_token = words[idx + 1]
            combined = token + next_token
            is_khmer_combined = any(('\u1780' <= c <= '\u17D3') for c in combined)
            if is_khmer_combined and combined not in dictionary and len(combined) > 2:
                # Find candidates for combined with edit distance = 1
                candidates = []
                L = len(combined)
                for l_candidate in range(max(1, L - 1), L + 2):
                    if l_candidate in dict_by_len:
                        for cand in dict_by_len[l_candidate]:
                            if edit_distance(combined, cand) == 1:
                                candidates.append(cand)
                                
                selected_cand = None
                if len(candidates) == 1:
                    selected_cand = candidates[0]
                elif len(candidates) > 1:
                    # Resolve ambiguity with context (previous word)
                    if idx > 0:
                        prev_word = words[idx - 1]
                        matching_cands = []
                        for cand in candidates:
                            if prev_word + cand in dictionary:
                                matching_cands.append(cand)
                        if len(matching_cands) == 1:
                            selected_cand = matching_cands[0]
                            
                    # Resolve ambiguity with context (next next word)
                    if selected_cand is None and idx < num_words - 2:
                        next_next_word = words[idx + 2]
                        matching_cands = []
                        for cand in candidates:
                            if cand + next_next_word in dictionary:
                                matching_cands.append(cand)
                        if len(matching_cands) == 1:
                            selected_cand = matching_cands[0]
                            
                if selected_cand is not None:
                    logger.info(f"Spell Corrector (Merged): Corrected combined '{combined}' to '{selected_cand}'")
                    corrected_words.append(selected_cand)
                    idx += 2  # Consume both tokens
                    continue
                    
        # Fallback to single token correction
        is_khmer_token = any(('\u1780' <= c <= '\u17D3') for c in token)
        if not is_khmer_token or len(token) <= 2 or token in dictionary:
            corrected_words.append(token)
            idx += 1
            continue
            
        candidates = []
        L = len(token)
        for l_candidate in range(max(1, L - 1), L + 2):
            if l_candidate in dict_by_len:
                for cand in dict_by_len[l_candidate]:
                    if edit_distance(token, cand) == 1:
                        candidates.append(cand)
                        
        if len(candidates) == 1:
            logger.info(f"Spell Corrector: Corrected '{token}' to '{candidates[0]}'")
            corrected_words.append(candidates[0])
        elif len(candidates) > 1:
            selected_cand = None
            if idx > 0:
                prev_word = corrected_words[-1] if corrected_words else words[idx - 1]
                matching_cands = []
                for cand in candidates:
                    if prev_word + cand in dictionary:
                        matching_cands.append(cand)
                if len(matching_cands) == 1:
                    selected_cand = matching_cands[0]
                    
            if selected_cand is None and idx < num_words - 1:
                next_word = words[idx + 1]
                matching_cands = []
                for cand in candidates:
                    if cand + next_word in dictionary:
                        matching_cands.append(cand)
                if len(matching_cands) == 1:
                    selected_cand = matching_cands[0]
                    
            if selected_cand is not None:
                logger.info(f"Spell Corrector (Context): Corrected '{token}' to '{selected_cand}'")
                corrected_words.append(selected_cand)
            else:
                corrected_words.append(token)
        else:
            corrected_words.append(token)
        idx += 1
        
    return "".join(corrected_words)

class OCRWorker(QThread):
    """
    A QThread worker to perform offline OCR in the background.
    Supports Kiri OCR (Deep learning-based) as the primary engine, 
    with a robust 3-Pass Parallel Tesseract Ensemble as a fallback.
    """
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, image: Image.Image):
        super().__init__()
        self.image = image

    def run(self):
        logger.info("OCR worker thread started.")
        
        # Determine whether to use Kiri OCR
        use_kiri = HAS_KIRI_OCR and (getattr(config, "OCR_ENGINE", "tesseract") == "kiri-ocr")
        
        try:
            raw_text = ""
            if use_kiri:
                kiri = get_kiri_ocr_instance()
                if kiri is not None:
                    logger.info("Running Kiri OCR (ONNX Inference)...")
                    with tempfile.TemporaryDirectory() as temp_dir:
                        temp_path = os.path.join(temp_dir, "capture.png")
                        self.image.save(temp_path)
                        raw_text, _ = kiri.extract_text(temp_path)
                else:
                    logger.warning("Kiri OCR initialization failed. Falling back to Tesseract.")
                    use_kiri = False
            
            # Run Tesseract fallback if Kiri is not used or failed
            if not use_kiri:
                logger.info("Running Tesseract Three-Pass Parallel OCR Ensemble...")
                raw_text = self._run_tesseract_ensemble()
                
            # --- Post-Processing Pipeline ---
            # 1. Vowel Reordering
            ordered_text = reorder_khmer_vowels(raw_text.strip())
            
            # 2. Unicode Normalization
            if HAS_KHMER_NORMALIZER:
                logger.info("Using Seanghay's Khmer Normalizer...")
                normalized_text = khmer_normalize(ordered_text)
            else:
                normalized_text = normalize_khmer_vowels(ordered_text)
                
            # 3. Spelling Error Correction
            corrected_text = correct_khmer_ocr_errors(normalized_text)
            
            # 4. Dictionary-based Spell Check
            final_text = correct_spelling_with_dictionary(corrected_text)
            
            logger.info(f"OCR complete. Characters recognized: {len(final_text)}")
            self.finished.emit(final_text)
            
        except Exception as e:
            err_msg = f"An unexpected error occurred during OCR: {str(e)}"
            logger.exception(err_msg)
            self.error.emit(err_msg)

    def _run_tesseract_ensemble(self) -> str:
        """Runs the 3-Pass Parallel Tesseract Ensemble (Grayscale, Binarized, Deslanted)."""
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
        
        # 4. Smart Adaptive Scaling
        # Tesseract performs best when character x-height is around 20-30 pixels.
        # If the image height is less than 300px, we scale it up to 300px to enlarge small text.
        # If it is already large, we keep it at 1x to prevent oversized distortion.
        w, h = base_img.size
        target_height = 300
        if h < target_height:
            scale_factor = target_height / h
            new_w = int(w * scale_factor)
            new_h = int(h * scale_factor)
            scaled_img = base_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            logger.info(f"Image height {h}px is small. Scaling up by {scale_factor:.2f}x to {new_h}px.")
        else:
            scaled_img = base_img
            logger.info(f"Image height {h}px is sufficient. Keeping 1x scale.")
        
        # --- Pass A: Standard Pipeline (Optimized for Thin/Standard Body Fonts) ---
        img_pass_a = scaled_img
        
        # --- Pass B: Binarized + Line-Erase Pipeline ---
        # Smart Adaptive Thresholding: Calculates threshold dynamically based on the image's mean brightness.
        mean_brightness = ImageStat.Stat(scaled_img).mean[0]
        threshold = max(110, min(200, int(mean_brightness * 0.85)))
        logger.info(f"Adaptive thresholding: mean brightness={mean_brightness:.1f}, selected threshold={threshold}")
        
        binarized_img = scaled_img.point(lambda p: 255 if p > threshold else 0)
        img_pass_b = self._remove_horizontal_lines(binarized_img.copy())
        
        # --- Pass C: Deslanted + Binarized + Line-Erase Pipeline (Optimized for Italic Formats) ---
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
        return best_text

    def _remove_horizontal_lines(self, image):
        """
        Scans a binarized image (L mode, 0=black text, 255=white background)
        and erases horizontal runs of black pixels that are longer
        than 20% of the image width. Optimized using fast C-level bounding
        box and row checks to skip blank padding rows immediately (80% faster).
        Thick & Skew-tolerant: Erases adjacent top/bottom pixels to ensure
        tilted or thick underlines are completely cleared.
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
                                # Also erase immediate top/bottom neighbors to handle thickness/skew
                                for rx in range(run_start, x):
                                    pixels[rx, y] = 255
                                    if y > 0 and pixels[rx, y-1] == 0:
                                        pixels[rx, y-1] = 255
                                    if y < height - 1 and pixels[rx, y+1] == 0:
                                        pixels[rx, y+1] = 255
                            run_start = None
                            
                # Check at the end of the row
                if run_start is not None:
                    run_length = width - run_start
                    if run_length > line_threshold:
                        for rx in range(run_start, width):
                            pixels[rx, y] = 255
                            if y > 0 and pixels[rx, y-1] == 0:
                                pixels[rx, y-1] = 255
                            if y < height - 1 and pixels[rx, y+1] == 0:
                                pixels[rx, y+1] = 255
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
