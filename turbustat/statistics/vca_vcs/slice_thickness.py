# Licensed under an MIT open source license - see LICENSE
from __future__ import print_function, absolute_import, division

import numpy as np
from astropy import units as u
from spectral_cube.spectral_cube import BaseSpectralCube
from astropy.convolution import Gaussian1DKernel
from warnings import warn


def spectral_regrid_cube(cube, channel_width, method='downsample',
                         downsamp_function=np.nanmean):
    '''
    Spectrally regrid a SpectralCube to a given channel width. There are two
    options for regridding:

    * `method='downsample'` -- The data are downsampled by averaging over an
    integer number of channels. The initial assumption is that the
    channels are uncorrelated. This is the default setting.

    * `method='regrid'` -- The data are spectrally smoothed with a Gaussian
    kernel. The kernel width is the target channel width deconvolved from
    the current channel width
    (http://spectral-cube.readthedocs.io/en/latest/smoothing.html#spectral-smoothing).
    In order to ensure the regridded cube covers the same spectral
    range, the smoothed cube may have channels that differ slightly from the
    given width. The number of channels is chosen to be the next lowest
    integer when dividing the original number of channels by the ratio of the
    new and old channel widths.

    Typically the downsample method should be used. If the channel widths is
    being increased by less than the line width, there will not be a
    substantial difference in the power-law slopes using the different methods.
    However, the prior smoothing required for the interpolation step with
    `method='regrid'` makes the effective channel width wider. This effect
    should be accounted for when estimating the transition from the thin to
    thick velocity regimes (e.g., in VCA), as the channel
    size will not be the effective channel width when using this method.

    Parameters
    ----------
    cube : `~spectral_cube.SpectralCube`
        Spectral cube to regrid.
    channel_width : `~astropy.units.Quantity` or int
        The width of the new channels. If `method='regrid'`, `channel_width`
        should be given in equivalent spectral units used in the cube, or
        in pixel units. For example, downsampling by a factor of 2 for a cube
        with a channel width of 0.1 km/s can be achieved by setting
        `channel_width` to `2 * u.pix`
        or `0.2 km /s`. If `method='downsample'`, `channel_width` must be
        an integer. This sets the number of channels to downsample across.
    method : {'downsample', 'regrid'}, optional
        Method to spectrally regrid the cube.
    downsamp_function : {function}, optional
        The operation to apply when downsampling. Defaults to
        `~numpy.nanmean`.

    Returns
    -------
    regridded_cube : `spectral_cube.SpectralCube`
        The regridded or downsampled cube.
    '''

    if not isinstance(cube, BaseSpectralCube):
        raise TypeError("`cube` must be a SpectralCube object.")

    if method not in ['regrid', 'downsample']:
        raise ValueError("method must be 'regrid' or 'downsample'. {} was"
                         " given".format(method))

    if method == 'downsample':

        if not isinstance(channel_width, int):
            raise TypeError("channel_width must be an integer when using "
                            "method='downsample'.")

        return cube.downsample_axis(channel_width, axis=0)

    else:
        # Must then be regrid

        if not isinstance(channel_width, u.Quantity):
            raise TypeError("channel_width must be an "
                            "astropy.units.Quantity when using "
                            "method='regrid'.")

        fwhm_factor = np.sqrt(8 * np.log(2))

        pix_unit = channel_width.unit.is_equivalent(u.pix)

        spec_width = np.diff(cube.spectral_axis[:2])[0]

        current_resolution = np.diff(cube.spectral_axis[:2])[0]

        if pix_unit:
            target_resolution = channel_width.value * spec_width
        else:
            target_resolution = channel_width.to(current_resolution.unit)

        diff_factor = np.abs(target_resolution / current_resolution).value

        if diff_factor == 1:
            warn("The requested channel width match the original channel "
                 "width. The original cube is returned.")
            return cube

        if diff_factor < 1:
            raise ValueError("Only down-sampling the spectral grid is"
                             " supported. The requested channel width of {0}"
                             " is a factor {1} "
                             "smaller than the original channel width."
                             .format(target_resolution, diff_factor))

        pixel_scale = np.abs(current_resolution)

        gaussian_width = ((target_resolution**2 - current_resolution**2)**0.5 /
                          pixel_scale / fwhm_factor)
        kernel = Gaussian1DKernel(gaussian_width)
        new_cube = cube.spectral_smooth(kernel)

        # Now define the new spectral axis at the new resolution
        num_chan = int(np.floor_divide(cube.shape[0], diff_factor))
        new_specaxis = np.linspace(cube.spectral_axis.min().value,
                                   cube.spectral_axis.max().value,
                                   num_chan) * current_resolution.unit

        # Keep the same order (max to min or min to max)
        if current_resolution.value < 0:
            new_specaxis = new_specaxis[::-1]

        return new_cube.spectral_interpolate(new_specaxis,
                                             suppress_smooth_warning=True)
