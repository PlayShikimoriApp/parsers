#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import sys
import pickle
import pandas as pd

from collections import OrderedDict
from functools import lru_cache
from sqlalchemy import create_engine

from parsers import ongoings, anime365, sovetromantica, sibnet, anilibria, misc
from parsers.tools import catch
from shikimori import routes, models

def import_to_db(from_pickle = False):
	engine = create_engine(open(".env").read(), echo=True)
	index = routes.get_index(models.AnimeVideo)

	if not from_pickle:
		result = find_all_ongoings()
	else:
		result = pickle.load(open("ongoings.pkl", "rb"))

	result["id"] = range(index + 1, index + len(result)  + 1)
	result.to_sql(name='anime_videos', con=engine, if_exists = 'append', index=False)

def save(pd_dataframe, from_pickle = False, format = "sql"):
	if not from_pickle:
		result = pd_dataframe
	else:
		result = pickle.load(open("ongoings.pkl", "rb"))

	if format == "pkl":
		pickle.dump(result, open("ongoings.pkl", "wb"))
	elif format == "sql":
		table = result.values.tolist()
		header = "INSERT INTO anime_videos (" + ", ".join(result.columns) + ") VALUES "
		res = [header]
		for row in table:
			res.append("(" +", ".join(["\"%s\"" %i for i in row]) + "),")

		res[-1] = res[-1][:-1] + ";"
		open("ongoings.sql", "wb").write("\n".join(res).encode("u8"))

def find_animes(parsers = OrderedDict([
			("anilibria", anilibria.AnilibriaParser),
			("smotretanime", anime365.Anime365Parser),
			("sovetromantica", sovetromantica.SRParser),
			("sibnet", sibnet.SibnetParser)
		      ]),
		      anime_ids = [],
		      fetch_only_ongoings = True,
		      fetch_all_episodes = False,
		      filter_by_unique_url = True,
		      use_anime_aliases = True):

	ongoings.main()
	if fetch_only_ongoings:
		anime_ids = ongoings.ONGOING_IDS
	else:
		anime_ids = [i for i in anime_ids if not i in ongoings.ONGOING_IDS]

	result = pd.DataFrame(columns = ["anime_id", "anime_english", "anime_russian", "watches_count", "uploader", "url", "episode", "kind", "quality", "language", "author"])
	for hosting, Parser in parsers.items():
		print("hosting: " + hosting)
		parser = Parser()
		total = len(anime_ids)
		for n, id in enumerate(anime_ids, start = 1):
			note = "found"
			shiki_ongoing_data = {}
			try:
				anime_info = routes.get_anime_info(id)
			except:
				if not fetch_only_ongoings:
					note = "not found"
					print("[%d / %d]: %s: %s" % (n, total, anime_info["anime_english"], note))
					continue
				catch()
				shiki_ongoing_data = ongoings.parse_ongoing(ongoings.get_ongoing_html(id))
				if not shiki_ongoing_data["anime_russian"] or not shiki_ongoing_data["anime_english"]:
					note = "not found in database and couldn't retrieve anime names, skipping"
					print("[%d / %d]: %s: %s" % (n, total, anime_info["anime_english"], note))
					continue

				note = "not found in database, will create first entries"
				anime_info = {
					"anime_english": shiki_ongoing_data["anime_english"],
					"anime_russian": shiki_ongoing_data["anime_russian"],
					"duration": 	 0
				}
				print("[%d / %d] %s: %s" % (n, total, anime_info["anime_english"], note))

			if anime_info["anime_english"] in misc.SKIP:
				note = "anime was explicitly specified to skip fetch"
				print("[%d / %d] %s: %s" % (n, total, anime_info["anime_english"], note))
				continue


			search_kwargs = {}

			if fetch_only_ongoings:
				if not shiki_ongoing_data:
					shiki_ongoing_data = ongoings.parse_ongoing(ongoings.get_ongoing_html(id))

				if shiki_ongoing_data["type"]:
					#print("type: %s" % shiki_ongoing_data["type"])
					search_kwargs["type_"] = shiki_ongoing_data["type"]

			if use_anime_aliases:
				search_kwargs["anime_aliases"] = [anime_info["anime_russian"]]

			if not parser.search_anime(anime_info["anime_english"], **search_kwargs):
				note = "not found"
				print("[%d / %d] %s: %s" % (n, total, anime_info["anime_english"], note))
				continue


			max_episode = routes.get_max_episode_for_hosting(id, hosting)
			episode_from = 1
			episode_to = 1

			# HAX: more appropriate solution?
			# When fetching non-ongoings, set episode_to to high value for now to fetch all episodes.
			if not fetch_only_ongoings:
				episode_to = 9999
			if fetch_only_ongoings:
				if not fetch_all_episodes:
					latest = 1 if parser.fetch_latest_episode else 0

					if shiki_ongoing_data["episodes_available"] - (1 - latest) <= max_episode:
						note = "already fetched all available episodes"
						print("[%d / %d] %s: %s" % (n, total, anime_info["anime_english"], note))
						continue

					episode_from = max_episode + 1
					episode_to = shiki_ongoing_data["episodes_available"] + latest
				else:
					episode_from = 1
					if shiki_ongoing_data:
						episode_to = shiki_ongoing_data["episodes_available"] + 1

			print("[%d / %d] %s: %s" % (n, total, anime_info["anime_english"], note))
			tmp_videos_list = pd.DataFrame(columns = ["url", "episode", "kind", "quality", "video_hosting", "language", "author"])
			for episode_num in range(episode_from, episode_to):
				df = parser.get_videos_list(anime_info["anime_english"], episode_num)
				if (isinstance(df, type(None))) or df.empty:
					note = "no videos found"
					if not fetch_only_ongoings:
						note = "the max boundary episode_to was not specified."
						note += " Skipping fetch because episode %d was not found." % episode_num
						print("[%d / %d] %s (%d / %d): %s" % (n, total, anime_info["anime_english"], episode_num, episode_to, note))
						break
					print("[%d / %d] %s (%d / %d): %s" % (n, total, anime_info["anime_english"], episode_num, episode_to, note))

				print("[%d / %d] %s (%d / %d)" % (n, total, anime_info["anime_english"], episode_num, episode_to))
				tmp_videos_list = tmp_videos_list.append(df, ignore_index = True, sort = False)

			tmp_videos_list["anime_id"] = str(id)
			tmp_videos_list["anime_english"] = anime_info["anime_english"]
			tmp_videos_list["anime_russian"] = anime_info["anime_russian"]
			tmp_videos_list["watches_count"] = "0"
			tmp_videos_list["uploader"] = "importbot"
			del tmp_videos_list["video_hosting"]
			#print(tmp_videos_list.values.tolist())
			if filter_by_unique_url:
				ongoing_all_videos = [o.url for o in models.AnimeVideo.query.filter(models.AnimeVideo.anime_id == id).all()]
				tmp_videos_list = tmp_videos_list[~tmp_videos_list.url.isin(ongoing_all_videos)]
			
			result = result.append(tmp_videos_list, ignore_index = True, sort = False)
	return result
