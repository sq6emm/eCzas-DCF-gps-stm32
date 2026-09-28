"""shared IF -> USB-audio conversion"""
def if_to_usb(x, fs, car, at=1000.0, invert=False):
    """real IF -> 8 kHz 'USB audio', carrier at `at` Hz: carrier to 0 Hz, complex low-pass +-900 Hz
    (one side only: nothing from below the carrier folds in), back up to `at`, real part.
    invert: the IF spectrum is mirrored (IC-7610: RF f -> 12 kHz - (f - dial)); conjugated at 0 Hz."""
    import numpy as np, scipy.signal as ss
    n = np.arange(len(x))
    z = ss.lfilter(ss.firwin(601, 900, fs=fs), 1, x * np.exp(-2j * np.pi * car / fs * n))
    z = z[:: fs // 8000]
    if invert: z = np.conj(z)
    return (z * np.exp(2j * np.pi * at / 8000 * np.arange(len(z)))).real
