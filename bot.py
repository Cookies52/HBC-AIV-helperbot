import os
import logging
import pywikibot
import re
import time
import mwparserfromhell
import ipaddress
import pywikibot.logentries
import pywikibot.pagegenerators
import traceback

directory = os.path.dirname(os.path.realpath(__file__))

logger = logging.getLogger(__name__)
logging.basicConfig(format='%(asctime)s %(levelname)-8s %(message)s',
                    filename=os.path.join(directory, 'aivBot.log'),
                    level=logging.INFO)
logging.getLogger().addHandler(logging.StreamHandler())

SETTING_REGEX = r"<!-- v[0-9]\.[0-9]\.[0-9]{1,3} RemoveBlocked=([ofnOFN]{2,3}) MergeDuplicates=([ofnOFN]{2,3}) AutoMark=([ofnOFN]{2,3}) FixInstructions=([ofnOFN]{2,3}) AutoBacklog=([ofnOFN]{2,3}) AddLimit=([0-9]{1,2}) RemoveLimit=([0-9]{1,2}) -->"
pages_to_watch = [
   'Wikipedia:Administrator intervention against vandalism',
   'Wikipedia:Administrator intervention against vandalism/TB2',
   'Wikipedia:Usernames for administrator attention',
   'Wikipedia:Usernames for administrator attention/Bot'
]

IP_Sections = [
    "== Listed at [[Wikipedia:Sensitive IP addresses]] =="
]

Cat_Section = [
    "== Sockpuppet related ==",
    "== Misc ==",
    "== Shared =="
]

enwiki = pywikibot.Site("en", 'wikipedia')
special_ips = {}
special_cats = []
instructions = []

def get_ip_list():
    logger.debug("Fetching special IP list")

    page = pywikibot.Page(enwiki, title="User:HBC AIV helperbot/Special IPs")
    for line in page.text.split("\n"):
        if line != '' and line[0] == ";":
            d = line.strip(";").split(":",1)
            if d[0] != '':
                for address in ipaddress.ip_network(d[0]):
                    special_ips[str(address)] = d[1]
        elif line[0:14] == "* [[:Category:":
            special_cats.append(line[5:-2])


while True:
    get_ip_list()
    for pagetitle in pages_to_watch:
        try:
            removed = 0
            to_remove = []
            page = pywikibot.Page(enwiki, title=pagetitle)
            content = mwparserfromhell.parse(page.text)
            # Calculate users left
            all_temps = content.filter_templates()
            vandals = [t for t in all_temps if t.name.lower() in ["vandal", "ipvandal", "user-uaa"]]
            vandalCount = len(vandals)

            # First, get page settings
            settings = re.search(SETTING_REGEX, page.text)
            RemovedBlocked = (settings.group(1).upper() == "ON")
            MergeDuplicates = (settings.group(2).upper() == "ON")
            AutoMark = (settings.group(3).upper() == "ON")
            FixInstructions = (settings.group(4).upper() == "ON")
            AutoBacklog =  (settings.group(5).upper() == "ON")
            AddLimit = int(settings.group(6))
            RemoveLimit = int(settings.group(7))

            logger.info("Updated Settings for %s: %s,%s,%s,%s,%s,%s,%s", page.title(), RemovedBlocked, MergeDuplicates, AutoMark, FixInstructions, AutoBacklog, AddLimit,
                        RemoveLimit)
            lines = page.text.split("\n")

            for idx, f in enumerate(lines):
                temps = mwparserfromhell.parse(f).filter_templates()
                v = [t for t in temps if t.name.lower() in ["vandal", "ipvandal", "user-uaa"]]
                for t in v:
                    username = str(t.get("1")).strip()
                    if username[0:2] == "1=":
                        username = username[2:]

                    userInfo = pywikibot.User(enwiki, username)
                    partialBlock = True

                    # check tags
                    if "<!--marked-->" not in f and AutoMark:
                        if userInfo.isAnonymous():
                            if username in special_ips:
                                content.replace(f, f+"<!--marked-->\n:*'''Note:''' "+special_ips[username] + ". ~~~~")
                                page.text = content
                                logging.info("Marking %s as a sensitive IP", username)
                                page.save(minor=False, summary=str(vandalCount)+" reports remaining. Commenting on " + username + " : Sensitive IP")
                                break
                        # Get user categories
                        for cat in userInfo.categories():
                            if cat.title() in special_cats:
                                content.replace(f, f+"<!--marked-->\n:*'''Note:''' User is in the category: "+ cat + ". ~~~~")
                                page.text = content
                                logging.info("Marking %s as belonging to an important category", username)
                                page.save(minor=False, summary=str(vandalCount)+" reports remaining. Commenting on " + username + " : User is in the category " + cat)
                                break
                    isLocked = False
                    if not userInfo.isAnonymous():
                       try:
                          isLocked = userInfo.is_locked()
                       except Exception:
                          isLocked = False
                    if userInfo.is_blocked() or isLocked:
                        anon_only = False
                        props = userInfo.getprops()
                        block_info=None
                        if userInfo.isAnonymous():
                            block_info = enwiki.blocks(iprange=username)
                            # check if user in special groups
                            for block in block_info:
                                if 'anononly' in block:
                                    anon_only = True
                                if "partial" not in block:
                                    partialBlock = False
                        else:
                            block_info = enwiki.blocks(users=username)
                            for block in block_info:
                                if "partial" not in block:
                                    partialBlock = False

                        counter = idx
                        while RemovedBlocked and counter < len(lines):
                            if lines[counter] == "":
                                counter += 1

                            elif lines[counter] == f:
                                if counter != len(lines) - 1 and lines[counter+1] == "*":
                                    if counter + 2 < len(lines):
                                        content.remove(lines[counter]+"\n*\n")
                                        logging.info("Blank bullet found after entry %s, removing", username)
                                    elif counter + 1 < len(lines):
                                        content.remove(lines[counter] + "\n*")
                                        logging.info("Blank bullet found at end of page after entry %s, removing", username)
                                    counter += 2
                                elif counter == len(lines) - 1:
                                    content.remove(f)
                                    logging.info("Removing entry for user %s at end of page", username)
                                    break
                                else:
                                    content.remove(f+"\n")
                                    counter += 1
                                    logging.info("Removing entry for user %s, continuing checks", username)            

                            elif lines[counter][0:2] == "*:" or lines[counter][0:2] == "**" or lines[counter][0] == ":":
                                if counter == len(lines)-1:
                                    content.remove(lines[counter])
                                    logging.info("Removing comment for user %s at end of page", username)
                                    break
                                else:
                                    content.remove(lines[counter]+"\n")
                                    logging.info("Removing comment for user %s, continuing checks", username)
                                counter += 1
                            else:
                                break

                        vandalCount -= 1
                        flags = []
                        summary = str(vandalCount) + " users left, rm [[Special:Contributions/" + username +"|" + username + "]]"
                        if "blockedby" in props and props["blockedby"] != "":
                            if "blockexpiry" in props and props["blockexpiry"] == "infinite":
                                summary += " (blocked indef by " + props["blockedby"]
                            else:
                                summary += " (blocked by " + props["blockedby"]
                            summary += ")"

                        if "blockowntalk" in props:
                            flags.append("TPD")
                        if "blockemail" in props:
                            flags.append("EMD")
                        if "blocknocreate" in props:
                            flags.append("ACB")
                        if anon_only:
                            flags.append("AO")

                        if len(flags) != 0:
                            summary += " ([[User:HBC AIV helperbot/Legend|" + " ".join(flags) + "]])"
                        logging.info('Saving with summary "%s"', summary)
                        page.text = content
                        page.save(summary=summary, minor=False)
                        time.sleep(5)
                        break

            page = pywikibot.Page(enwiki, title=pagetitle)
            content = mwparserfromhell.parse(page.text)
            all_temps = mwparserfromhell.parse(content).filter_templates()
            vandals = [t for t in all_temps if t.name.lower() in ["vandal", "ipvandal", "user-uaa"]]
            vandalCount = len(vandals)
            if AutoBacklog:
                for t in all_temps:
                    if t.name == "noadminbacklog":
                        if vandalCount >= AddLimit:
                            logging.info("Marking %s as backlogged", page.title())
                            newt = mwparserfromhell.nodes.Template(name="adminbacklog")
                            newt.add("bot", "HBC AIV helperbot14")
                            content.replace(t, newt)
                            page.text = content
                            page.save(summary=str(vandalCount)+" reports remaining.")
                    if t.name == "adminbacklog":
                        if vandalCount <= RemoveLimit:
                            logging.info("Marking %s as unbacklogged", page.title())
                            newt = mwparserfromhell.nodes.Template(name="noadminbacklog")
                            newt.add("bot", "HBC AIV helperbot14")
                            content.replace(t, newt)
                            page.text = content
                            page.save(summary=str(vandalCount)+" reports remaining. Noticeboard is no longer backlogged")
        except Exception as e:
            logging.exception(e)
            print(e)
            continue 
   
    time.sleep(60 * 5) # wait 5 mins between runs
