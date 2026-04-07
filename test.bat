@echo off
ffmpeg -y -i "C:\Users\ericm\Downloads\airtable_extract\videos\recWQnHo3nj2wc175_pexels.mp4" -vf "drawtext=text=TEST:fontfile=C\:/Windows/Fonts/arial.ttf:fontsize=72:fontcolor=white:x=100:y=100" -c:a copy "C:\Users\ericm\Downloads\airtable_extract\videos\test_draw.mp4"
