content = open("testbed/a.md", encoding="utf-8").read()
assert "bar" in content, "foo 没被改成 bar"
print("验证通过: foo 已改成 bar")
