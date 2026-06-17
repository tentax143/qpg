import zipfile

path = r"D:\GIT REPO MAIN\qpg\core\data\base.docx"
with zipfile.ZipFile(path) as z:
    print("=== header1.xml ===")
    with z.open("word/header1.xml") as f:
        print(f.read().decode('utf-8'))

    print("\n=== document.xml.rels ===")
    with z.open("word/_rels/document.xml.rels") as f:
        print(f.read().decode('utf-8'))
