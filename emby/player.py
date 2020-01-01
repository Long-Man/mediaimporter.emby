#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2017-2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import time
from uuid import uuid4

import xbmc
import xbmcmediaimport

from emby.api import Api
from emby.constants import EMBY_PROTOCOL, \
    PLAYING_PLAY_METHOD_DIRECT_STREAM, \
    PLAYING_PROGRESS_EVENT_TIME_UPDATE, PLAYING_PROGRESS_EVENT_PAUSE, PLAYING_PROGRESS_EVENT_UNPAUSE
from emby.server import Server

from lib.utils import log, mediaProvider2str

class Player(xbmc.Player):
    def __init__(self, progressInterval=None):
        super(xbmc.Player, self).__init__()

        self._progressInterval = progressInterval or 10
        self._lastProgressReport = None

        self._providers = {}

        self._file = None
        self._item = None
        self._itemId = None
        self._mediaProvider = None
        self._playSessionId = None
        self._paused = False

    def AddProvider(self, mediaProvider):
        if not mediaProvider:
            raise ValueError('invalid mediaProvider')

        self._providers[mediaProvider.getIdentifier()] = mediaProvider

    def RemoveProvider(self, mediaProvider):
        if not mediaProvider:
            raise ValueError('invalid mediaProvider')

        del self._providers[mediaProvider.getIdentifier()]

    def Process(self):
        if not self._lastProgressReport:
            return

        # adhere to the configured progress interval
        if (time.time() - self._lastProgressReport) < self._progressInterval:
            return

        self._reportPlaybackProgress()

    def onPlayBackStarted(self):
        self._reset()
        self._file = self.getPlayingFile()

    def onAVStarted(self):
        self._startPlayback()

    def onPlayBackSeek(self, time, seekOffset):
        self._reportPlaybackProgress()

    def onPlayBackSeekChapter(self, chapter):
        self._reportPlaybackProgress()

    def onPlayBackPaused(self):
        self._paused = True
        self._reportPlaybackProgress(event=PLAYING_PROGRESS_EVENT_PAUSE)

    def onPlayBackResumed(self):
        self._paused = False
        self._reportPlaybackProgress(event=PLAYING_PROGRESS_EVENT_UNPAUSE)

    def onPlayBackStopped(self):
        self._stopPlayback()

    def onPlayBackEnded(self):
        self._stopPlayback()

    def onPlayBackError(self):
        self._stopPlayback(failed=True)

    def _reset(self):
        self._file = None
        self._item = None
        self._itemId = None
        self._mediaProvider = None
        self._playSessionId = None
        self._paused = False

    def _startPlayback(self):
        if not self._file:
            return

        if not self.isPlayingVideo():
            return

        videoInfoTag = self.getVideoInfoTag()
        if not videoInfoTag:
            return

        self._itemId = videoInfoTag.getUniqueID(EMBY_PROTOCOL)
        if not self._itemId:
            return

        for mediaProvider in self._providers.values():
            importedItems = xbmcmediaimport.getImportedItemsByProvider(mediaProvider)
            matchingItems = [ importedItem for importedItem in importedItems \
                if importedItem.getVideoInfoTag() and importedItem.getVideoInfoTag().getUniqueID(EMBY_PROTOCOL) == self._itemId ]
            if not matchingItems:
                continue

            if len(matchingItems) > 1:
                log('multiple items imported from {} match the imported Emby item {} playing from {}' \
                    .format(mediaProvider2str(mediaProvider), self._itemId, self._file), xbmc.LOGWARNING)

            self._item = matchingItems[0]
            self._mediaProvider = mediaProvider
            break

        if not self._item:
            return

        # generate a session identifier
        self._playSessionId = str(uuid4()).replace("-", "")

        # prepare the data of the API call
        data = self._preparePlayingData(stopped=False)

        # tell the Emby server that a library item is being played
        server = Server(self._mediaProvider)
        url = server.BuildSessionsPlayingUrl()
        server.ApiPost(url, data)

        self._lastProgressReport = time.time()

    def _reportPlaybackProgress(self, event=PLAYING_PROGRESS_EVENT_TIME_UPDATE):
        if not self._item:
            return

        # prepare the data of the API call
        data = self._preparePlayingData(stopped=False, event=event)

        # tell the Emby server that a library item is being played
        server = Server(self._mediaProvider)
        url = server.BuildSessionsPlayingProgressUrl()
        server.ApiPost(url, data)

        self._lastProgressReport = time.time()

    def _stopPlayback(self, failed=False):
        if not self._item:
            return

        # prepare the data of the API call
        data = self._preparePlayingData(stopped=True, failed=failed)

        # tell the Emby server that a library item is being played
        server = Server(self._mediaProvider)
        url = server.BuildSessionsPlayingStoppedUrl()
        server.ApiPost(url, data)

        self._reset()

    def _preparePlayingData(self, stopped=False, event=None, failed=False):
        data = {
            'ItemId': self._itemId,
            'PlaySessionId': self._playSessionId,
            'PlaylistIndex': 0,
            'PlaylistLength': 1,
        }

        if stopped:
            data.update({
                'Failed': failed
            })
        else:
            data.update({
                'QueueableMediaTypes': 'Audio,Video',
                'CanSeek': True,
                'PlayMethod': PLAYING_PLAY_METHOD_DIRECT_STREAM,
                'IsPaused': self._paused,
            })

            try:
                data.update({
                    'PositionTicks': Api.secondsToTicks(self.getTime()),
                    'RunTimeTicks': Api.secondsToTicks(self.getTotalTime()),
                })
            except Exception:
                pass

            if event:
                data.update({
                    'EventName': event
                })

        return data
