@echo off
ffmpeg -y -i "C:\Users\ericm\Downloads\airtable_extract\videos\recRdCkBP6sa6JFMs_pexels.mp4" -vf "ass=\\?\C:\Users\ericm\Downloads\airtable_extract\videos\recRdCkBP6sa6JFMs_captioned.ass" -c:a copy "C:\Users\ericm\Downloads\airtable_extract\videos\recRdCkBP6sa6JFMs_captioned.mp4"
