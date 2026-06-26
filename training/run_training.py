import os
import sys
import subprocess
import argparse

# Try to locate Tesseract on Windows or macOS
def find_tesseract_cmd():
    if sys.platform == "win32":
        search_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expandvars(r"%USERPROFILE%\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        ]
        for p in search_paths:
            if os.path.exists(p):
                return p
        return "tesseract.exe"
    return "tesseract"

def find_tessdata_dir(tesseract_cmd):
    # Standard location next to tesseract.exe on Windows
    if sys.platform == "win32" and os.path.isabs(tesseract_cmd):
        tessdata = os.path.join(os.path.dirname(tesseract_cmd), "tessdata")
        if os.path.exists(tessdata):
            return tessdata
    # macOS Homebrew standard locations
    mac_paths = [
        "/opt/homebrew/share/tessdata",
        "/usr/local/share/tessdata"
    ]
    for p in mac_paths:
        if os.path.exists(p):
            return p
    return None

def run_command(cmd, shell=False):
    print(f"Executing: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    try:
        result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=shell)
        return result.stdout, result.stderr
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {e}")
        print(f"Stdout: {e.stdout}")
        print(f"Stderr: {e.stderr}")
        raise

def start_training(training_dir, max_iterations):
    print("==================================================")
    print("  Automated Tesseract LSTM Training Orchestrator  ")
    print("==================================================")
    
    # 1. Locate Tesseract and training tools
    tesseract_cmd = find_tesseract_cmd()
    tessdata_dir = find_tessdata_dir(tesseract_cmd)
    
    if not tessdata_dir or not os.path.exists(os.path.join(tessdata_dir, "khm.traineddata")):
        print(f"Error: Could not locate 'khm.traineddata' in your Tesseract 'tessdata' folder.")
        print(f"Please ensure Tesseract is installed and the Khmer language pack is present.")
        return
        
    tessdata_khm_path = os.path.join(tessdata_dir, "khm.traineddata")
    tesseract_dir = os.path.dirname(tesseract_cmd) if os.path.isabs(tesseract_cmd) else ""
    
    # Define paths for training tools
    combine_cmd = os.path.join(tesseract_dir, "combine_tessdata.exe") if tesseract_dir and sys.platform == "win32" else "combine_tessdata"
    lstmtraining_cmd = os.path.join(tesseract_dir, "lstmtraining.exe") if tesseract_dir and sys.platform == "win32" else "lstmtraining"
    
    print(f"Tesseract Path: {tesseract_cmd}")
    print(f"Tessdata Path: {tessdata_dir}")
    
    if not os.path.exists(training_dir):
        print(f"Error: Training data directory '{training_dir}' does not exist.")
        print("Please run 'auto_generate_system_training.py' first to generate the training pairs.")
        return
        
    # 2. Find all generated .tif files
    tif_files = [f for f in os.listdir(training_dir) if f.endswith(".tif")]
    if not tif_files:
        print(f"Error: No .tif training files found in '{training_dir}'.")
        return
        
    print(f"\nFound {len(tif_files)} training pairs. Converting to .lstmf format...")
    
    # 3. Convert .tif/.box pairs to .lstmf files
    for tif in tif_files:
        base_name = os.path.splitext(tif)[0]
        tif_path = os.path.join(training_dir, tif)
        box_path = os.path.join(training_dir, f"{base_name}.box")
        
        if not os.path.exists(box_path):
            print(f"Warning: Box file missing for '{tif}', skipping.")
            continue
            
        # Command: tesseract <tif_path> <output_base> lstm.train
        output_base = os.path.join(training_dir, base_name)
        cmd = [tesseract_cmd, tif_path, output_base, "lstm.train"]
        try:
            run_command(cmd)
        except Exception:
            print("Failed to convert pairs. Exiting.")
            return

    # 4. Extract the base LSTM model from existing khm.traineddata
    print("\nExtracting the base LSTM model from existing khm.traineddata...")
    base_lstm_path = os.path.join(training_dir, "khm.lstm")
    cmd_extract = [combine_cmd, "-e", tessdata_khm_path, base_lstm_path]
    try:
        run_command(cmd_extract)
        print("Successfully extracted base khm.lstm model.")
    except Exception:
        print("Failed to extract base model. Make sure Tesseract training tools are installed.")
        return

    # 5. Verify train_listfile.txt contains correct paths
    list_file_path = os.path.join(training_dir, "train_listfile.txt")
    if not os.path.exists(list_file_path):
        # Create it if missing
        lstmf_files = [f for f in os.listdir(training_dir) if f.endswith(".lstmf")]
        with open(list_file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lstmf_files) + "\n")
            
    # Modify the listfile to use absolute paths so lstmtraining doesn't get lost
    with open(list_file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    abs_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if not os.path.isabs(line):
            abs_lines.append(os.path.abspath(os.path.join(training_dir, line)))
        else:
            abs_lines.append(line)
            
    with open(list_file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(abs_lines) + "\n")

    # 6. Start the actual neural network training (lstmtraining)
    print(f"\nStarting neural network training for {max_iterations} iterations...")
    print("This will adjust the weights of the neural network to learn your custom fonts.")
    print("Hold tight, this runs a deep-learning loop in your console...")
    
    model_output_prefix = os.path.join(training_dir, "output_model")
    cmd_train = [
        lstmtraining_cmd,
        "--model_output", model_output_prefix,
        "--continue_from", base_lstm_path,
        "--traineddata", tessdata_khm_path,
        "--train_listfile", list_file_path,
        "--max_iterations", str(max_iterations)
    ]
    
    try:
        # Run training (this might take a few minutes depending on max_iterations)
        run_command(cmd_train)
    except Exception as e:
        print(f"\nTraining interrupted or failed: {e}")
        print("Note: If it completed some iterations, a checkpoint file was created in the output directory.")
        return

    # 7. Compile the final trained model
    print("\nTraining complete! Compiling the final khm.traineddata model...")
    checkpoint_path = f"{model_output_prefix}_checkpoint"
    final_model_path = os.path.join(training_dir, "khm.traineddata")
    
    if not os.path.exists(checkpoint_path):
        # Find the latest checkpoint file if the exact named one isn't there
        checkpoints = [f for f in os.listdir(training_dir) if f.startswith("output_model_") and not f.endswith(".lstm")]
        if checkpoints:
            checkpoints.sort()
            checkpoint_path = os.path.join(training_dir, checkpoints[-1])
            
    if not os.path.exists(checkpoint_path):
        print(f"Error: Could not find checkpoint file at '{checkpoint_path}' to compile the model.")
        return
        
    cmd_compile = [
        lstmtraining_cmd,
        "--stop_training",
        "--continue_from", checkpoint_path,
        "--traineddata", tessdata_khm_path,
        "--model_output", final_model_path
    ]
    
    try:
        run_command(cmd_compile)
        print("\n==================================================")
        print("  CONGRATULATIONS! TRAINING COMPLETE!")
        print("==================================================")
        print(f"Successfully compiled model: {final_model_path}")
        print(f"\nTo deploy this new model, copy it to your Tesseract directory:")
        print(f"  Copy-Item -Path \"{final_model_path}\" -Destination \"{tessdata_khm_path}\" -Force")
        print("==================================================")
    except Exception:
        print("Failed to compile final trained model.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automate the Tesseract LSTM Khmer training process: convert pairs, extract base model, run training, and compile the final model.")
    parser.add_argument("--dir", default="system_training_data", help="Directory containing the TIFF/Box training pairs.")
    parser.add_argument("--iterations", type=int, default=400, help="Number of training iterations (default: 400).")
    args = parser.parse_args()
    
    start_training(args.dir, args.iterations)
