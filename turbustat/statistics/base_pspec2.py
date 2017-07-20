# Licensed under an MIT open source license - see LICENSE


import numpy as np
import statsmodels.api as sm
import warnings
import astropy.units as u

from .lm_seg import Lm_Seg
from .psds import pspec
from .fitting_utils import clip_func


class StatisticBase_PSpec2D(object):
    """
    Common features shared by 2D power spectrum methods.
    """

    @property
    def ps2D(self):
        '''
        Two-dimensional power spectrum.
        '''
        return self._ps2D

    @property
    def ps1D(self):
        '''
        One-dimensional power spectrum.
        '''
        return self._ps1D

    @property
    def ps1D_stddev(self):
        '''
        1-sigma standard deviation of the 1D power spectrum.
        '''
        if not self._stddev_flag:
            Warning("ps1D_stddev is only calculated when return_stddev"
                    " is enabled.")

        return self._ps1D_stddev

    @property
    def freqs(self):
        '''
        Corresponding spatial frequencies of the 1D power spectrum.
        '''
        return self._freqs

    @property
    def wavenumbers(self):
        return self._freqs * min(self._ps2D.shape)

    def compute_radial_pspec(self, return_stddev=True,
                             logspacing=True, max_bin=None, **kwargs):
        '''
        Computes the radially averaged power spectrum.

        Parameters
        ----------
        return_stddev : bool, optional
            Return the standard deviation in the 1D bins.
        logspacing : bool, optional
            Return logarithmically spaced bins for the lags.
        max_bin : float, optional
            Maximum spatial frequency to bin values at.
        kwargs : passed to `~turbustat.statistics.psds.pspec`.
        '''

        if return_stddev:
            self._freqs, self._ps1D, self._ps1D_stddev = \
                pspec(self.ps2D, return_stddev=return_stddev,
                      logspacing=logspacing, max_bin=max_bin, **kwargs)
            self._stddev_flag = True
        else:
            self._freqs, self._ps1D = \
                pspec(self.ps2D, return_stddev=return_stddev, max_bin=max_bin,
                      **kwargs)
            self._stddev_flag = False

        # Attach units to freqs
        self._freqs = self.freqs / u.pix

    def fit_pspec(self, brk=None, log_break=False, low_cut=None,
                  high_cut=None, min_fits_pts=10, verbose=False):
        '''
        Fit the 1D Power spectrum using a segmented linear model. Note that
        the current implementation allows for only 1 break point in the
        model. If the break point is estimated via a spline, the breaks are
        tested, starting from the largest, until the model finds a good fit.

        Parameters
        ----------
        brk : float or None, optional
            Guesses for the break points. If given as a list, the length of
            the list sets the number of break points to be fit. If a choice is
            outside of the allowed range from the data, Lm_Seg will raise an
            error. If None, a spline is used to estimate the breaks.
        log_break : bool, optional
            Sets whether the provided break estimates are log-ed (base 10)
            values. This is disabled by default. When enabled, the brk must
            be a unitless `~astropy.units.Quantity`
            (`u.dimensionless_unscaled`).
        low_cut : `~astropy.units.Quantity`, optional
            Lowest frequency to consider in the fit.
        high_cut : `~astropy.units.Quantity`, optional
            Highest frequency to consider in the fit.
        min_fits_pts : int, optional
            Sets the minimum number of points needed to fit. If not met, the
            break found is rejected.
        verbose : bool, optional
            Enables verbose mode in Lm_Seg.
        '''

        # Make the data to fit to
        if low_cut is None:
            # Default to the largest frequency, since this is just 1 pixel
            # in the 2D PSpec.
            self.low_cut = 1. / (0.5 * float(max(self.ps2D.shape)) * u.pix)
        else:
            self.low_cut = self._to_pixel_freq(low_cut)

        if high_cut is None:
            self.high_cut = (self.freqs.max().value + 1) / u.pix
        else:
            self.high_cut = self._to_pixel_freq(high_cut)

        x = np.log10(self.freqs[clip_func(self.freqs.value, self.low_cut.value,
                                          self.high_cut.value)].value)
        y = np.log10(self.ps1D[clip_func(self.freqs.value, self.low_cut.value,
                                         self.high_cut.value)])

        if brk is not None:
            # Try the fit with a break in it.
            if not log_break:
                brk = self._to_pixel_freq(brk).value
                brk = np.log10(brk)
            else:
                # A value given in log shouldn't have dimensions
                if hasattr(brk, "unit"):
                    assert brk.unit == u.dimensionless_unscaled
                    brk = brk.value

            brk_fit = \
                Lm_Seg(x, y, brk)
            brk_fit.fit_model(verbose=verbose)

            if brk_fit.params.size == 5:

                # Check to make sure this leaves enough to fit to.
                if sum(x < brk_fit.brk) < min_fits_pts:
                    warnings.warn("Not enough points to fit to." +
                                  " Ignoring break.")

                    self._brk = None
                else:
                    good_pts = x.copy() < brk_fit.brk
                    x = x[good_pts]
                    y = y[good_pts]

                    self._brk = 10**brk_fit.brk / u.pix
                    self._brk_err = np.log(10) * self.brk.value * \
                        brk_fit.brk_err / u.pix

                    self._slope = brk_fit.slopes
                    self._slope_err = brk_fit.slope_errs

                    self.fit = brk_fit.fit

            else:
                self._brk = None
                # Break fit failed, revert to normal model
                warnings.warn("Model with break failed, reverting to model\
                               without break.")
        else:
            self._brk = None
            self._brk_err = None

        if self.brk is None:
            x = sm.add_constant(x)

            model = sm.OLS(y, x, missing='drop')

            self.fit = model.fit()

            self._slope = self.fit.params[1]
            self._slope_err = self.fit.bse[1]

    @property
    def slope(self):
        '''
        Power spectrum slope(s).
        '''
        return self._slope

    @property
    def slope_err(self):
        '''
        1-sigma error on the power spectrum slope(s).
        '''
        return self._slope_err

    @property
    def brk(self):
        '''
        Fitted break point.
        '''
        return self._brk

    @property
    def brk_err(self):
        '''
        1-sigma on the break point.
        '''
        return self._brk_err

    def plot_fit(self, show=True, show_2D=False, color='r', label=None,
                 symbol="D", xunit=u.pix**-1, save_name=None,
                 use_wavenumber=False):
        '''
        Plot the fitted model.
        '''

        import matplotlib.pyplot as p

        if use_wavenumber:
            xlab = r"k / (" + xunit.to_string() + ")"
        else:
            xlab = r"Spatial Frequency (" + xunit.to_string() + ")"

        # 2D Spectrum is shown alongside 1D. Otherwise only 1D is returned.
        if show_2D:
            p.subplot(122)
            p.imshow(np.log10(self.ps2D), interpolation="nearest",
                     origin="lower")
            p.colorbar()

            ax = p.subplot(121)
        else:
            ax = p.subplot(111)

        good_interval = clip_func(self.freqs.value, self.low_cut.value,
                                  self.high_cut.value)

        y_fit = self.fit.fittedvalues
        fit_index = np.logical_and(np.isfinite(self.ps1D), good_interval)

        # Set the x-values to use (freqs or k)
        if use_wavenumber:
            xvals = self.wavenumbers
        else:
            xvals = self.freqs

        xvals = self._spatial_freq_unit_conversion(xvals, xunit).value

        if self._stddev_flag:
            ax.errorbar(np.log10(xvals),
                        np.log10(self.ps1D),
                        yerr=0.434 * (self.ps1D_stddev / self.ps1D),
                        color=color,
                        fmt=symbol, markersize=5, alpha=0.5, capsize=10,
                        elinewidth=3)

            ax.plot(np.log10(xvals[fit_index]), y_fit, color + '-',
                    label=label, linewidth=2)
            ax.set_xlabel("log " + xlab)
            ax.set_ylabel(r"log P$_2(K)$")

        else:
            ax.loglog(self.xvals[fit_index], 10**y_fit, color + '-',
                      label=label, linewidth=2)

            ax.loglog(self.xvals, self.ps1D, color + symbol, alpha=0.5,
                      markersize=5)

            ax.set_xlabel(xlab)
            ax.set_ylabel(r"P$_2(K)$")

        # Show the fitting extents
        low_cut = self._spatial_freq_unit_conversion(self.low_cut, xunit).value
        high_cut = \
            self._spatial_freq_unit_conversion(self.high_cut, xunit).value
        low_cut = low_cut if not use_wavenumber else \
            low_cut * min(self._ps2D.shape)
        high_cut = high_cut if not use_wavenumber else \
            high_cut * min(self._ps2D.shape)
        p.axvline(np.log10(low_cut), color=color, alpha=0.5, linestyle='--')
        p.axvline(np.log10(high_cut), color=color, alpha=0.5, linestyle='--')

        p.grid(True)

        if save_name is not None:
            p.savefig(save_name)

        if show:
            p.show()
