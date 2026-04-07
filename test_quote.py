import subprocess
import imageio_ffmpeg

video = r'C:\Users\ericm\Downloads\airtable_extract\videos\recRdCkBP6sa6JFMs_pexels.mp4'
ass = r'C:\Users\ericm\Downloads\airtable_extract\videos\recRdCkBP6sa6JFMs_captioned.ass'
output = r'C:\Users\ericm\Downloads\airtable_extract\videos\test_quote.mp4'

ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
# Try with double backslash for cmd
vf = 'ass="C:\\Users\\ericm\\Downloads\\airtable_extract\\videos\\recRdCkBP6sa6JFMs_captioned.ass"'
cmd = [ffmpeg, '-y', '-i', video, '-vf', vf, '-c:a', 'copy', output]
print('CMD:', cmd)
r = subprocess.run(cmd, capture_output=True, text=True)
print('RC:', r.returncode)
print('STDERR:', r.stderr[-500:] if r.stderr else 'None')
