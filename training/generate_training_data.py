import os
import sys
import argparse
from PIL import Image, ImageDraw, ImageFont

# High-density default Khmer training corpus containing standard letters, subscripts, diacritics, punctuation, and numbers
DEFAULT_KHMER_CORPUS = [
    "សួស្តីឆ្នាំថ្មី ឆ្នាំសកល ២០២៦ និងសូមស្វាគមន៍មកកាន់កម្មវិធីអានអត្ថបទខ្មែរ។",
    "ភាសាខ្មែរមានអក្សរ និងព្យញ្ជនៈសរុបចំនួន ៣៣ តួ ដែលបូករួមទាំងស្រៈពេញតួ និងស្រៈនិស្ស័យ។",
    "ជើងអក្សរទាំងអស់មាន៖ ្ក ្ខ ្គ ្ឃ ្ង ្ច ្ឆ ្ជ ្ឈ ្ញ ្ដ ្ឋ ្ឌ ្ឍ ្ណ ្ត ្ថ ្ទ ្ធ ្ន ្ប ្ផ ្ព ្ភ ្ម ្យ ្រ ្ល ្វ ្ស ្ហ ឡ ្អ។",
    "ស្រៈនិស្ស័យសំខាន់ៗរួមមាន៖ ា ិ ី ឹ ឺ ុ ូ ួ ើ ឿ ៀ េ ែ ៃ ោ ៅ ុំ ំ ាំ ះ ុះ េះ ោះ។",
    "និមិត្តសញ្ញានិងសញ្ញាវណ្ណយុត្តិ៖ (វង់ក្រចក) [របាំងមុខ] {រ៉ឺម៉ក} «សម្រង់សម្តី» ។ (ខណ្ឌ) ៖ (ពីរចុច) ។ះ",
    "លេខខ្មែរ៖ ០ ១ ២ ៣ ៤ ៥ ៦ ៧ ៨ ៩ និងលេខសកល៖ 0 1 2 3 4 5 6 7 8 9",
    "តើលោកអ្នកអាចអានអត្ថបទនេះដោយគ្មានបញ្ហាបានដែរឬទេ? សូមសាកល្បងទាំងអស់គ្នា។",
    "ការអភិវឌ្ឍន៍បច្ចេកវិទ្យា OCR ជួយសម្រួលដល់ការបម្លែងរូបភាពទៅជាអក្សរឌីជីថលប្រកបដោយប្រសិទ្ធភាពខ្ពស់។",
    "ខ្ញុំស្រឡាញ់ប្រទេសកម្ពុជា និងប្រជាជនខ្មែរទាំងអស់។ សូមឱ្យមានសេចក្តីសុខ និងសន្តិភាពជានិច្ច។",
    "អក្សរសិល្ប៍ខ្មែរមានប្រវត្តិសាស្ត្រយូរលង់ណាស់មកហើយ ចាប់តាំងពីសម័យនគរភ្នំមកម្ល៉េះ។"
]

def generate_box_and_tif(font_path, corpus_lines, output_base):
    print("==================================================")
    print("  Tesseract Training Data Generator for Khmer")
    print("==================================================")
    print(f"Font Path: {font_path}")
    print(f"Output Base: {output_base}")
    
    # 1. Setup font and size (Tesseract prefers 30-36px for training)
    font_size = 32
    try:
        font = ImageFont.truetype(font_path, font_size)
    except Exception as e:
        print(f"Error: Failed to load font '{font_path}': {e}")
        return False
        
    line_height = int(font_size * 1.6)
    margin = 50
    
    # 2. Calculate image dimensions
    # Create a temporary image to measure text widths
    temp_img = Image.new("L", (1, 1), 255)
    temp_draw = ImageDraw.Draw(temp_img)
    
    max_width = 0
    total_height = margin * 2
    valid_lines = []
    
    for line in corpus_lines:
        line = line.strip()
        if not line:
            continue
        # Measure line width
        bbox = temp_draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        max_width = max(max_width, w)
        total_height += line_height
        valid_lines.append(line)
        
    if not valid_lines:
        print("Error: No text found to render.")
        return False
        
    max_width += margin * 2
    
    print(f"Text Lines: {len(valid_lines)}")
    print(f"Target Image Size: {max_width}x{total_height} pixels")
    
    # 3. Create the training image (binary grayscale 'L' mode, white background)
    img = Image.new("L", (max_width, total_height), 255)
    draw = ImageDraw.Draw(img)
    
    box_entries = []
    
    # 4. Draw text and calculate bounding boxes
    current_y = margin
    for line in valid_lines:
        # Draw the line of text (black color)
        draw.text((margin, current_y), line, font=font, fill=0)
        
        # Tesseract box format: <char> <left> <bottom> <right> <top> <page>
        # Note: Tesseract's Y-coordinate system starts at the BOTTOM-LEFT of the image,
        # while Pillow's Y-coordinate system starts at the TOP-LEFT.
        # We invert the coordinates:
        # tess_bottom = image_height - pillow_bottom
        # tess_top = image_height - pillow_top
        
        current_x = margin
        for char in line:
            if char == " " or char == "\u200b": # Skip spaces/zero-width spaces in coordinate boxes
                # Standard spacing step
                bbox = draw.textbbox((0, 0), " ", font=font)
                current_x += (bbox[2] - bbox[0])
                continue
                
            # Get character bounding box
            char_bbox = draw.textbbox((current_x, current_y), char, font=font)
            cx1, cy1, cx2, cy2 = char_bbox
            
            # Convert to Tesseract coordinate system
            tess_left = cx1
            tess_bottom = total_height - cy2
            tess_right = cx2
            tess_top = total_height - cy1
            
            # Ensure the bounding box has a width and height of at least 1 pixel.
            # Tesseract rejects 0-width or 0-height boxes (e.g., combining vowels/diacritics) and exits with code 1.
            if tess_right <= tess_left:
                tess_right = tess_left + 1
            if tess_top <= tess_bottom:
                tess_top = tess_bottom + 1
                
            box_entries.append(f"{char} {tess_left} {tess_bottom} {tess_right} {tess_top} 0")
            
            # Move X coordinate forward by the width of this character
            char_w = cx2 - cx1
            if char_w > 0:
                current_x += char_w
            else:
                # Fallback spacing step for zero-width combinations
                bbox = draw.textbbox((0, 0), char, font=font)
                current_x += (bbox[2] - bbox[0])
                
        current_y += line_height
        
    # 5. Save TIFF image (uncompressed, standard for Tesseract)
    tiff_path = f"{output_base}.tif"
    img.save(tiff_path, "TIFF")
    print(f"Successfully saved training image: {tiff_path}")
    
    # 6. Save Box file (UTF-8 encoded)
    box_path = f"{output_base}.box"
    with open(box_path, "w", encoding="utf-8") as f:
        f.write("\n".join(box_entries) + "\n")
    print(f"Successfully saved box file: {box_path}")
    print("==================================================")
    print("  Generation Complete! Ready for Tesseract training.")
    print("==================================================")
    return True

def main():
    parser = argparse.ArgumentParser(description="Generate Tesseract OCR TIFF/Box training pairs for a custom Khmer font.")
    parser.add_argument("--font", required=True, help="Path to the custom .ttf font file.")
    parser.add_argument("--text", help="Path to a text file containing the Khmer training corpus (optional).")
    parser.add_argument("--output", default="khm.customfont.exp0", help="Base filename for the output .tif and .box files.")
    args = parser.parse_args()
    
    # Load corpus
    if args.text and os.path.exists(args.text):
        try:
            with open(args.text, "r", encoding="utf-8") as f:
                corpus_lines = f.readlines()
            print(f"Loaded custom corpus from: {args.text}")
        except Exception as e:
            print(f"Warning: Failed to load custom corpus: {e}. Falling back to default.")
            corpus_lines = DEFAULT_KHMER_CORPUS
    else:
        print("Using default high-density Khmer training corpus.")
        corpus_lines = DEFAULT_KHMER_CORPUS
        
    generate_box_and_tif(args.font, corpus_lines, args.output)

if __name__ == "__main__":
    main()
