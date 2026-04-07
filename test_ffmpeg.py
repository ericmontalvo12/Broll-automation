import subprocess
import os

video = r'C:\Users\ericm\Downloads\airtable_extract\videos\recWQnHo3nj2wc175_pexels.mp4'
output = r'C:\Users\ericm\Downloads\airtable_extract\videos\test_draw.mp4'

# Test with fontfile - use forward slashes
filter_test = 'drawtext=text=TEST:fontfile=C:/Windows/Fonts/arial.ttf:fontsize=72:fontcolor=white:x=100:y=100'
cmd = ['ffmpeg', '-y', '-i', video, '-vf', filter_test, '-c:a', 'copy', output]

print("Running:", ' '.join(cmd))
r = subprocess.run(cmd, capture_output=True, text=True)
print('RC:', r.returncode)
if r.returncode != 0:
    print('STDERR:', r.stderr[-500:])
else:
    print('Success!')
