# Dragon API

These functions, callbacks, objects, and exceptions make up natlink's
Dragon-facing public API.

## Connection And Lifecycle

### `natConnect`

::: natlink_compat.natConnect

### `natDisconnect`

::: natlink_compat.natDisconnect

### `waitForSpeech`

::: natlink_compat.waitForSpeech

### `isNatSpeakRunning`

::: natlink_compat.isNatSpeakRunning

## Callbacks

### `setBeginCallback`

::: natlink_compat.setBeginCallback

### `setChangeCallback`

::: natlink_compat.setChangeCallback

### `setTimerCallback`

::: natlink_compat.setTimerCallback

### `getCallbackDepth`

::: natlink_compat.getCallbackDepth

## Objects

### `GramObj`

::: natlink_compat.GramObj

### `ResObj`

::: natlink_compat.ResObj

### `DictObj`

::: natlink_compat.DictObj

## Users And Vocabulary

### User Profiles

::: natlink_compat.getAllUsers

::: natlink_compat.createUser

::: natlink_compat.openUser

::: natlink_compat.saveUser

::: natlink_compat.getCurrentUser

### Training

::: natlink_compat.getUserTraining

::: natlink_compat.getTrainingMode

::: natlink_compat.startTraining

::: natlink_compat.finishTraining

### Vocabulary

::: natlink_compat.getWordInfo

::: natlink_compat.addWord

::: natlink_compat.deleteWord

::: natlink_compat.setWordInfo

::: natlink_compat.getWordProns

## Exceptions

### `NatError`

::: natlink_compat.NatError

### `InvalidWord`

::: natlink_compat.InvalidWord

### `UnknownName`

::: natlink_compat.UnknownName

### `OutOfRange`

::: natlink_compat.OutOfRange

### `MimicFailed`

::: natlink_compat.MimicFailed

### `BadGrammar`

::: natlink_compat.BadGrammar

### `WrongState`

::: natlink_compat.WrongState

### `BadWindow`

::: natlink_compat.BadWindow

### `SyntaxError`

::: natlink_compat.SyntaxError

### `UserExists`

::: natlink_compat.UserExists

### `ValueError`

::: natlink_compat.ValueError

### `DataMissing`

::: natlink_compat.DataMissing

### `WrongType`

::: natlink_compat.WrongType
