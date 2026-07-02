from krutidev_unicode_converter import KrutiDevToUnicode

converter = KrutiDevToUnicode()

with open("input.txt", "r", encoding="utf-8") as f:
    text = f.read()

converted = converter.convert(text)

with open("output.txt", "w", encoding="utf-8") as f:
    f.write(converted)

print("Done!")