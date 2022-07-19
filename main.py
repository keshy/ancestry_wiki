import argparse
import random

from redisgraph import Graph, Node
import redis
from bs4 import BeautifulSoup
import requests
import argparse


class Person:
    def __init__(self, label="person", name="NoName", born=-1, died=-1, siblings='N/A', parents='N/A', children='N/A',
                 spouse='N/A',
                 url=None):
        self.name = name if not None else "N/A"
        self.born = born if not None else "N/A"
        self.died = died if not None else "N/A"
        self.siblings = siblings if not None else "N/A"
        self.children = children if not None else "N/A"
        self.parents = parents if not None else "N/A"
        self.spouse = spouse if not None else "N/A"
        self.url = url if not None else "N/A"
        self.label = label

    def get_person_dict(self):
        return Node(node_id=random.randint(0, 1000000), label=self.label, properties=self.__dict__).toString()


class AncestorCrawl:
    BORN = 'Born'
    DIED = "Died"
    SPOUSES = 'Spouses'
    SPOUSE = 'Spouse'
    CONSORT = 'Consort'
    CHILDREN = 'Children'
    PARENTS = 'Parents'
    PARENT_S = 'Parent(s)'
    WIKI_URL_PREFIX = 'https://en.wikipedia.org'
    RELATIVES = "Relatives"
    SIBLINGS = "Siblings"
    FAMILY = "Family"

    # direction 0 = sibling, 1 = spouse, -1 = Parent, 2 = children

    def __init__(self, host="localhost", port=6379):
        self.redis_connection = redis.Redis(host=host, port=port)
        self.graph = Graph('ancenstory_wiki', self.redis_connection)
        self.c_upward_count = 0
        self.c_downward_count = 0
        self.visitor = {}
        self.rtype = {
            1: "SPOUSE",
            2: "CHILD",
            -1: "PARENT",
            0: "SIBLING",
            3: "RELATIVE",
            4: "FAMILY"
        }

    def crawl(self, label, url, direction=0, limit=100000, prev=None):
        if limit == 0:
            print("Stopped due to limit on recursive depth")
            return

        try:
            response = requests.get(url=url)
            if response.status_code != 200:
                print(
                    "Got an unsuccessful response code %s from wikipedia. Stopping traversal at this level" % response.status_code)
            elif url in self.visitor.keys():
                return
            else:
                c_recurse = {}
                p_recurse = {}
                sib_recurse = {}
                sp_recurse = {}
                fm_recurse = {}
                self.visitor[url] = True
                t = response.text
                # check if there is vcard in the template.
                s = BeautifulSoup(t, 'html.parser')
                h = url.rsplit('/')[-1]
                m = s.find('table', class_='infobox')
                m_sub = []
                if m:
                    [m_sub.append(k) for k in m.find_all(class_='infobox-label')]
                m2 = s.find('table', class_='infobox biography vcard')
                if m2:
                    [m_sub.append(k) for k in m2.find_all(class_='infobox-label')]
                m3 = s.find('table', class_='infobox vcard')
                if m3:
                    [m_sub.append(k) for k in m3.find_all(class_='infobox-label')]
                b = d = sp = sib = fm = parent = child = "N/A"
                for i in m_sub:
                    if self.BORN == i.text:
                        b = i.findNext().text
                    elif self.DIED == i.text:
                        d = i.findNext().text
                    elif self.SPOUSE == i.text or self.SPOUSES == i.text or self.CONSORT == i.text:
                        sp = i.findNext().text
                        for x in i.findNext().find_all('a'):
                            if x.text.startswith('['):
                                continue
                            sp_recurse[x.text] = x['href']
                    elif self.CHILDREN == i.text:
                        child = i.findNext().text
                        for x in i.findNext().find_all('a'):
                            if x.text.startswith('['):
                                continue
                            c_recurse[x.text] = x['href']
                    elif self.PARENTS == i.text or self.PARENT_S == i.text:
                        parent = i.findNext().text
                        for x in i.findNext().find_all('a'):
                            if x.text.startswith('['):
                                continue
                            p_recurse[x.text] = x['href']
                    elif self.RELATIVES == i.text or self.SIBLINGS == i.text:
                        sib = i.findNext().text
                        for x in i.findNext().find_all('a'):
                            if x.text.startswith('['):
                                continue
                            sib_recurse[x.text] = x['href']
                    elif self.FAMILY == i.text:
                        fm = i.findNext().text
                        for x in i.findNext().find_all('a'):
                            if x.text.startswith('['):
                                continue
                            fm_recurse[x.text] = x['href']

                p = Person(label, h, b, d, parents=parent, siblings=sib, children=child, spouse=sp, url=url)
                self.graph.query("MERGE (n: %s%s)" % (p.label, p.get_person_dict()))
                self.graph.commit()
                if prev is not None:
                    # not root so assign edges
                    self.graph.query(
                        "MATCH (u: %s {name: \"%s\"}), (u2: %s {name: \"%s\"}) MERGE (u)-[r: %s]->(u2)" % (prev.label,
                                                                                                           prev.name,
                                                                                                           p.label,
                                                                                                           p.name,
                                                                                                           self.rtype.get(
                                                                                                               direction)))
                    self.graph.commit()

                limit -= 1
                for rl in c_recurse.keys():
                    self.crawl(label, self.WIKI_URL_PREFIX + c_recurse.get(rl), direction=2, limit=limit, prev=p)
                for rl in p_recurse.keys():
                    self.crawl(label, self.WIKI_URL_PREFIX + p_recurse.get(rl), direction=-1, limit=limit, prev=p)
                for rl in sp_recurse.keys():
                    self.crawl(label, self.WIKI_URL_PREFIX + sp_recurse.get(rl), direction=0, limit=limit, prev=p)
                for rl in sib_recurse.keys():
                    self.crawl(label, self.WIKI_URL_PREFIX + sib_recurse.get(rl), direction=3, limit=limit, prev=p)
                for rl in fm_recurse.keys():
                    self.crawl(label, self.WIKI_URL_PREFIX + fm_recurse.get(rl), direction=4, limit=limit, prev=p)
                print("Done with generation for url: %s " % url)

        except Exception as e:
            print("Got error from crawler as: ", e)


if __name__ == "__main__":
    ac = AncestorCrawl()
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('-u', '--url', required=True, type=str,
                            help="Starting Wikipedia URL to query ancestery from")
    arg_parser.add_argument('-e', '--epochs', default=100, type=int,
                            help="Number of epochs of levels to limit this crawl by")
    arg_parser.add_argument('-l', '--label', default='person', type=str,
                            help="Default label is person but can be used to enable segmentation")
    args = arg_parser.parse_args()
    ac.crawl(label=args.label, url=args.url, limit=args.epochs)
