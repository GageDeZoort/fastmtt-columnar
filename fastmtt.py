import os
import sys
import math
import vector as vec
import numpy as np
import numba as nb
import awkward as ak

@nb.jit(nopython=True, parallel=False)
def fastmtt(pt_1, eta_1, phi_1, mass_1, decay_type_1,
            pt_2, eta_2, phi_2, mass_2, decay_type_2,
            met_x, met_y, metcov_xx, metcov_xy, metcov_yx, metcov_yy,
            verbosity=-1, delta=1/1.15, reg_order=6,
            constrain=False, 
            constraint_window=np.array([124,126])):
    
    # initialize global parameters
    m_ele = 0.51100e-3
    m_muon = 0.10566
    m_tau = 1.77685
    m_pion = 0.13957
    mass_dict = {0: m_ele, 1: m_muon}
    
    # initialize higgs->ditau decays, tau decay types
    N = len(pt_1)
    m_tt_vis = np.zeros(N, dtype=np.float32)
    m_tt_opt = np.zeros(N, dtype=np.float32)

    # loop over all events, calculate corrected ditau mass
    for i in range(N):
        
        # grab the correct masses based on tau decay type
        # tau decay_type: 0 ==> leptonic to electron, 
        #                 1 ==> leptonic to muon, 
        #                 2 ==> leptonic to hadronic
        if (decay_type_1[i] != 2): m1 = mass_dict[decay_type_1[i]]
        else: m1 = mass1[i]
        if (decay_type_2[i] != 2): m2 = mass_dict[decay_type_2[i]]
        else: m2 = mass2[i]
            
        # store visible masses
        m_vis_1 = m1
        m_vis_2 = m2
        
        # determine minimum and maximum possible masses
        m_vis_min_1, m_vis_max_1 = 0, 0
        m_vis_min_2, m_vis_max_2 = 0, 0
        if (decay_type_1[i] == 0): m_vis_min_1, m_vis_max_1 = m_ele, m_ele
        if (decay_type_1[i] == 1): m_vis_min_1, m_vis_max_1 = m_muon, m_muon
        if (decay_type_1[i] == 2): m_vis_min_1, m_vis_max_1 = m_pion, 1.5
        if (decay_type_2[i] == 0): m_vis_min_2, m_vis_max_2 = m_ele, m_ele
        if (decay_type_2[i] == 1): m_vis_min_2, m_vis_max_2 = m_muon, m_muon
        if (decay_type_2[i] == 2): m_vis_min_2, m_vis_max_2 = m_pion, 1.5
        if (m_vis_1 < m_vis_min_1): m_vis_1 = m_vis_min_1
        if (m_vis_1 > m_vis_max_1): m_vis_1 = m_vis_max_1
        if (m_vis_2 < m_vis_min_2): m_vis_2 = m_vis_min_2
        if (m_vis_2 > m_vis_max_2): m_vis_2 = m_vis_max_2
          
        # store both tau candidate four vectors
        leg1 = vec.obj(pt=pt_1[i], eta=eta_1[i], phi=phi_1[i], mass=m_vis_1)
        leg2 = vec.obj(pt=pt_2[i], eta=eta_2[i], phi=phi_2[i], mass=m_vis_2)

        # store visible mass of ditau pair
        m_vis = math.sqrt(2*leg1.pt*leg2.pt*(math.cosh(leg1.eta - leg2.eta) - 
                                             math.cos(leg1.phi - leg2.phi)))
        m_tt_vis[i] = m_vis
            
        # correct initial visible masses
        if (decay_type_1[i] == 2 and m_vis_1 > 1.5): m_vis_1 = 0.3
        if (decay_type_2[i] == 2 and m_vis_2 > 1.5): m_vis_2 = 0.3

        # invert met covariance matrix, calculate determinant
        metcovinv_xx, metcovinv_yy = metcov_yy[i], metcov_xx[i]
        metcovinv_xy, metcovinv_yx = -metcov_xy[i], -metcov_yx[i]
        metcovinv_det = (metcovinv_xx*metcovinv_yy -
                         metcovinv_yx*metcovinv_xy)
        if (metcovinv_det<1e-10): 
                print("Warning! Ill-conditioned MET covariance at event index", i)
                continue
               
        # perform likelihood scan 
        # see http://cms.cern.ch/iCMS/jsp/openfile.jsp?tp=draft&files=AN2019_032_v3.pdf
        met_const = 1/(2*math.pi*math.sqrt(metcovinv_det))
        min_likelihood, x1_opt, x2_opt = 999, 0, 0
        mass_likelihood, met_transfer = 0, 0
        
        # scan over weights for each ditau four-vector
        for x1 in np.arange(0, 1, 0.01):
            for x2 in np.arange(0, 1, 0.01):
                x1_min = min(1, math.pow((m_vis_1/m_tau), 2))
                x2_min = min(1, math.pow((m_vis_2/m_tau),2))
                if ((x1 < x1_min) or (x2 < x2_min)): 
                    continue
        
                # test weighted four-vectors
                leg1_x1, leg2_x2 = leg1*(1/x1), leg2*(1/x2)
                ditau_test = vec.obj(px=leg1_x1.px+leg2_x2.px,
                                     py=leg1_x1.py+leg2_x2.py,
                                     pz=leg1_x1.pz+leg2_x2.pz,
                                     E=leg1_x1.E+leg2_x2.E)
                nu_test = vec.obj(px=ditau_test.px-leg1.px-leg2.px, 
                                  py=ditau_test.py-leg1.py-leg2.py,
                                  pz=ditau_test.pz-leg1.pz-leg2.pz,
                                  E=ditau_test.E-leg1.E-leg2.E)
                test_mass = ditau_test.mass
                if (((test_mass < constraint_window[0]) or
                     (test_mass > constraint_window[1])) and
                    constrain): continue 
            
                # calculate mass likelihood integral 
                m_shift = test_mass * delta
                if (m_shift < m_vis): continue 
                x1_min = min(1.0, math.pow((m_vis_1/m_tau),2))
                x2_min = max(math.pow((m_vis_2/m_tau),2), 
                             math.pow((m_vis/m_shift),2))
                x2_max = min(1.0, math.pow((m_vis/m_shift),2)/x1_min)
                if (x2_max < x2_min): continue
                J = 2*math.pow(m_vis,2) * math.pow(m_shift, -reg_order)
                I_x2 = math.log(x2_max) - math.log(x2_min)
                I_tot = I_x2
                if (decay_type_1[i] != 2):
                    I_m_nunu_1 = math.pow((m_vis/m_shift),2) * (math.pow(x2_max,-1) - math.pow(x2_min,-1))
                    I_tot += I_m_nunu_1
                if (decay_type_2[i] != 2):
                    I_m_nunu_2 = math.pow((m_vis/m_shift),2) * I_x2 - (x2_max - x2_min)
                    I_tot += I_m_nunu_2
                mass_likelihood = 1e9 * J * I_tot
                
                # calculate MET transfer function 
                residual_x = met_x[i] - nu_test.x
                residual_y = met_y[i] - nu_test.y
                pull2 = (residual_x*(metcovinv_xx*residual_x + 
                                     metcovinv_xy*residual_y) +
                         residual_y*(metcovinv_yx*residual_x +
                                     metcovinv_yy*residual_y))
                pull2 /= metcovinv_det
                met_transfer = met_const*math.exp(-0.5*pull2)
                
                # calculate final likelihood, store if minimum
                likelihood = -met_transfer * mass_likelihood 
                if (likelihood < min_likelihood):
                    min_likelihood = likelihood
                    x1_opt, x2_opt = x1, x2
                
        leg1_x1, leg2_x2 = leg1*(1/x1_opt), leg2*(1/x2_opt)
        p4_ditau_opt = vec.obj(px=leg1_x1.px+leg2_x2.px,
                               py=leg1_x1.py+leg2_x2.py,
                               pz=leg1_x1.pz+leg2_x2.pz,
                               E=leg1_x1.E+leg2_x2.E)
        m_tt_opt[i] = p4_ditau_opt.mass
            
    return {'m_tt_vis': m_tt_vis,
            'm_tt_opt': m_tt_opt}



infile = np.load(sys.argv[1])
N = int(sys.argv[2])
pt1, pt2 = infile['pt3'][:N], infile['pt4'][:N]
eta1, eta2 = infile['eta3'][:N], infile['eta4'][:N]
phi1, phi2 = infile['phi3'][:N], infile['phi4'][:N]
mass1, mass2 = infile['mass3'][:N], infile['mass4'][:N]
decay_type_1 = np.ones(len(pt1), dtype=np.uint8)[:N]
decay_type_2 = 2*np.ones(len(pt1), dtype=np.uint8)[:N]
metx, mety = infile['METx'][:N], infile['METy'][:N]
metcov_xx = infile['METcov_00'][:N]
metcov_xy = infile['METcov_01'][:N]
metcov_yx = infile['METcov_10'][:N]
metcov_yy = infile['METcov_11'][:N]

print(fastmtt(pt1, eta1, phi1, mass1, decay_type_1,
              pt2, eta2, phi2, mass2, decay_type_2,
              metx, mety,
              metcov_xx, metcov_xy, metcov_yx, metcov_yy,
              verbosity=-1, delta=1/1.15, reg_order=6))


