import moviepy as mp

print("Testing moviepy...")
video = mp.VideoFileClip(r"C:\Users\ericm\Downloads\airtable_extract\videos\recWQnHo3nj2wc175_pexels.mp4")
print(f"Video loaded: {video.size}, {video.duration}s")

txt = mp.TextClip(
    text="TEST",
    font="C:/Windows/Fonts/arial.ttf",
    font_size=48,
    color='cyan',
    stroke_color='black',
    stroke_width=3,
    duration=1,
    method='caption',
    size=video.size
)
print("Text clip created")

final = mp.CompositeVideoClip([video, txt.with_position(('center', 'bottom'))])
print("Composite created")

final.write_videofile(r"C:\Users\ericm\Downloads\airtable_extract\videos\test_moviepy.mp4", 
                      codec='libx264', audio_codec='copy', logger=None)
print("Done!")
