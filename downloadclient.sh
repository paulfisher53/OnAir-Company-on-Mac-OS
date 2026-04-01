#!/bin/bash

# 1. Setup variables
VERSION="1_6_27_2"
BASE_URL="https://auth.onair.company/download_x64/Application%20Files/OnAir%20Company_$VERSION"
TARGET_DIR="$HOME/Documents/OnAirCompanyClient"

# Maximum number of parallel downloads
MAX_PARALLEL=8

# 2. Create the directory and move into it
mkdir -p "$TARGET_DIR"
cd "$TARGET_DIR" || exit

# Clear existing files to ensure clean installation
echo "--- Clearing existing files ---"
rm -rf ./*
echo "Target directory cleared"

echo "--- Downloading Manifest ---"
curl -L -f --compressed --connect-timeout 10 --max-time 30 -o "OnAir.manifest" "$BASE_URL/OnAir%20Company.exe.manifest"

if [ ! -f "OnAir.manifest" ]; then
    echo "ERROR: Could not download manifest. Check your version number."
    exit 1
fi

# 3. Scrape and recreate directory structure
echo "--- Recreating Folder Structure and Downloading ---"

# Function to download a single file
download_file() {
    local win_path="$1"
    local unix_path="$2"
    local url_filename="$3"
    
    # Try .deploy first, then raw
    if curl -L -s -f --compressed --connect-timeout 10 --max-time 60 --retry 2 -o "$unix_path" "$BASE_URL/$url_filename.deploy" 2>/dev/null; then
        if [ -s "$unix_path" ]; then
            echo "✓ Downloaded: $unix_path"
            return 0
        fi
    fi
    
    # Try without .deploy extension
    if curl -L -s -f --compressed --connect-timeout 10 --max-time 60 --retry 2 -o "$unix_path" "$BASE_URL/$url_filename" 2>/dev/null; then
        if [ -s "$unix_path" ]; then
            echo "✓ Downloaded: $unix_path"
            return 0
        fi
    fi
    
    echo "✗ Failed: $unix_path"
    rm -f "$unix_path"
    return 1
}

# First, create all necessary directories
echo "Creating directory structure..."
{
    grep -oE 'file name="[^"]+"' "OnAir.manifest" | sed 's/file name="//;s/"//'
    grep -oE 'codebase="[^"]+"' "OnAir.manifest" | sed 's/codebase="//;s/"//'
} | while read -r win_path; do
    unix_path=$(echo "$win_path" | tr '\\' '/')
    dir_path=$(dirname "$unix_path")
    
    if [ "$dir_path" != "." ]; then
        mkdir -p "$dir_path"
    fi
done

# Extract all file names to a temporary file for processing
temp_file=$(mktemp)
{
    grep -oE 'file name="[^"]+"' "OnAir.manifest" | sed 's/file name="//;s/"//'
    grep -oE 'codebase="[^"]+"' "OnAir.manifest" | sed 's/codebase="//;s/"//'
} > "$temp_file"

# Count total files for progress tracking
total_files=$(wc -l < "$temp_file")
echo "Starting parallel download of $total_files files (max $MAX_PARALLEL concurrent)..."

# Debug: Show first few files to download
echo "Sample files to download:"
head -5 "$temp_file" | while read -r file; do
    echo "  - $file"
done

# Process files in batches for parallel downloading using simple background jobs
active_jobs=0

while IFS= read -r win_path; do
    # Convert Windows \ to Unix /
    unix_path=$(echo "$win_path" | tr '\\' '/')
    
    # Encode spaces and backslashes for the URL
    url_filename=$(echo "$win_path" | sed 's/ /%20/g; s/\\/%5C/g')
    
    # Wait if we've hit the parallel limit
    while [ $active_jobs -ge $MAX_PARALLEL ]; do
        # Count currently running background jobs
        active_jobs=$(jobs -r | wc -l)
        if [ $active_jobs -ge $MAX_PARALLEL ]; then
            sleep 0.1  # Brief pause before checking again
        fi
    done
    
    # Start download in background
    download_file "$win_path" "$unix_path" "$url_filename" &
    active_jobs=$((active_jobs + 1))
    
done < "$temp_file"

# Wait for all remaining downloads to complete
wait

echo "All file downloads completed!"

# Clean up temporary file
rm -f "$temp_file"

# 4. Final download of the main .exe
echo "--- Downloading Main Executable ---"
curl -L -f --compressed --connect-timeout 10 --max-time 60 --retry 2 -o "OnAir Company.exe" "$BASE_URL/OnAir%20Company.exe.deploy"

if [ -s "OnAir Company.exe" ]; then
    echo "✓ Main executable downloaded successfully"
else
    echo "✗ Failed to download main executable"
fi

echo "--- Done! All files organized in $TARGET_DIR ---"