from poolos.commands import Command,CommandAction
def test_command():
 c=Command(target="pump",action=CommandAction.SET,value=2500)
 assert c.target=="pump"
 assert c.value==2500
