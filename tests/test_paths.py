from flcmd import paths


def test_canon_posix():
    assert paths.canon("/home//user/") == "/home/user"
    assert paths.canon("/") == "/"
    assert paths.canon("a\\b\\c") == "a/b/c"


def test_canon_windows():
    assert paths.canon("C:\\Users\\x\\") == "C:/Users/x"
    assert paths.canon("c:") == "C:/"
    assert paths.canon("C:/") == "C:/"


def test_canon_unc():
    assert paths.canon("\\\\srv\\share\\dir") == "//srv/share/dir"
    assert paths.canon("//srv/share/") == "//srv/share"


def test_is_root():
    assert paths.is_root("/")
    assert paths.is_root("C:/")
    assert paths.is_root("//srv/share")
    assert not paths.is_root("/home")
    assert not paths.is_root("C:/x")
    assert not paths.is_root("//srv/share/dir")


def test_parent():
    assert paths.parent("/home/user") == "/home"
    assert paths.parent("/home") == "/"
    assert paths.parent("/") == "/"
    assert paths.parent("C:/x/y") == "C:/x"
    assert paths.parent("C:/x") == "C:/"
    assert paths.parent("C:/") == "C:/"
    assert paths.parent("//srv/share/dir") == "//srv/share"
    assert paths.parent("//srv/share") == "//srv/share"


def test_join():
    assert paths.join("/home", "user", "docs") == "/home/user/docs"
    assert paths.join("/", "etc") == "/etc"
    assert paths.join("C:/", "x") == "C:/x"
    assert paths.join("/a", "b/c") == "/a/b/c"


def test_basename_splitext():
    assert paths.basename("/a/b/c.txt") == "c.txt"
    assert paths.splitext("archive.tar.gz") == ("archive.tar", "gz")
    assert paths.splitext(".bashrc") == (".bashrc", "")
    assert paths.splitext("noext") == ("noext", "")


def test_native_roundtrip():
    p = "C:/Users/x/file.txt"
    n = paths.to_native(p)
    if paths.IS_WIN:
        assert "\\" in n
    else:
        assert n == p
    assert paths.from_native(n) == p
